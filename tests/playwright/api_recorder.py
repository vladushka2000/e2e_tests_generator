import asyncio
import json
import queue
import sys
import threading
import base64
from datetime import datetime

from playwright.async_api import async_playwright


class SimpleAPIRecorder:
    def __init__(self):
        self.captured_requests = []
        self.is_recording = False
        self.should_exit = False
        self.command_queue = queue.Queue()
        self.page = None

    async def start(self, url=None):
        """Запускает запись"""
        if not url:
            url = await self._ask_url()

        # Добавляем протокол если нет
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url

        # Запускаем поток для чтения команд
        input_thread = threading.Thread(target=self._read_commands, daemon=True)
        input_thread.start()

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=False)
                self.page = await browser.new_page()

                # Настраиваем перехват
                await self._setup_interception()

                print(f"\n🎥 API Recorder запущен")
                print(f"URL: {url}")
                print(f"Запись: {'ВКЛЮЧЕНА' if self.is_recording else 'ВЫКЛЮЧЕНА'}")
                print("\nКоманды: start, stop, save, exit")

                # Открываем страницу
                try:
                    await self.page.goto(url, timeout=30000)
                    print(f"✅ Страница загружена")
                except Exception as e:
                    print(f"⚠️ Не удалось загрузить страницу: {e}")

                while not self.should_exit:
                    await self._process_queued_commands()
                    await asyncio.sleep(0.1)

            finally:
                if browser:
                    await browser.close()

    async def _ask_url(self):
        """Запрашивает URL"""
        print("\nВведите URL для записи (по умолчанию: http://localhost:5173):")
        url_input = input().strip() or "http://localhost:5173"
        # Добавляем протокол если нет
        if not url_input.startswith(('http://', 'https://')):
            url_input = 'http://' + url_input
        return url_input

    def _read_commands(self):
        """Читает команды из консоли"""
        while not self.should_exit:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip().lower()
                if cmd:
                    self.command_queue.put(cmd)
            except:
                break

    async def _process_queued_commands(self):
        """Обрабатывает команды"""
        try:
            while True:
                cmd = self.command_queue.get_nowait()
                await self._process_command(cmd)
        except queue.Empty:
            pass

    async def _process_command(self, cmd):
        """Обрабатывает команду"""
        if cmd == "exit":
            self.should_exit = True
            print("🛑 Выход...")
        elif cmd == "start":
            self.is_recording = True
            print("🎬 Запись ВКЛЮЧЕНА")
        elif cmd == "stop":
            self.is_recording = False
            print("⏸ Запись ВЫКЛЮЧЕНА")
        elif cmd == "save":
            await self._save_to_file()
        else:
            print(f"❓ Неизвестная команда: {cmd}")

    async def _setup_interception(self):
        """Настраивает перехват запросов"""

        async def intercept_response(response):
            if not self.is_recording:
                return

            request = response.request
            try:
                # Получаем заголовки ответа (используем await!)
                response_headers_array = await response.headers_array()
                response_headers = {}
                for header in response_headers_array:
                    response_headers[header['name']] = header['value']

                # Получаем заголовки запроса (используем await!)
                request_headers_array = await request.headers_array()
                request_headers = {}
                for header in request_headers_array:
                    request_headers[header['name']] = header['value']

                # Получаем тело ответа
                content_type = response_headers.get('Content-Type', response_headers.get('content-type', ''))
                response_body = None
                is_binary = False

                # Пытаемся получить как текст, если не бинарный
                try:
                    # Проверяем, может ли быть текстовым
                    if any(ct in (content_type or '').lower() for ct in
                           ['text/', 'json', 'xml', 'html', 'javascript', 'css', 'application/json']):
                        response_body = await response.text()
                    else:
                        # Пробуем получить как байты
                        body_bytes = await response.body()
                        response_body = base64.b64encode(body_bytes).decode('utf-8')
                        is_binary = True
                except Exception as e:
                    # Если ошибка, пробуем получить как байты
                    try:
                        body_bytes = await response.body()
                        response_body = base64.b64encode(body_bytes).decode('utf-8')
                        is_binary = True
                    except Exception as e2:
                        print(f"❌ Ошибка получения тела ответа: {e2}")
                        response_body = None

                # Получаем тело запроса
                request_body = None
                request_post_data = request.post_data

                if request_post_data:
                    # Проверяем Content-Type запроса
                    req_content_type = request_headers.get('Content-Type', request_headers.get('content-type', ''))

                    if 'multipart/form-data' in (req_content_type or '').lower():
                        # Для multipart пытаемся сохранить как есть
                        try:
                            # Если данные большие, кодируем в base64
                            if len(request_post_data) > 10000:  # 10KB порог
                                request_body = base64.b64encode(
                                    request_post_data.encode('utf-8', errors='ignore')
                                    if isinstance(request_post_data, str)
                                    else request_post_data
                                ).decode('utf-8')
                            else:
                                request_body = request_post_data
                        except:
                            request_body = None
                    else:
                        # Для других типов пробуем как текст
                        try:
                            request_body = request_post_data
                        except:
                            request_body = None

                # Сохраняем запрос
                captured = {
                    'timestamp': datetime.now().isoformat(),
                    'url': request.url,
                    'method': request.method,
                    'request': {
                        'headers': request_headers,
                        'body': request_body,
                    },
                    'response': {
                        'status': response.status,
                        'headers': response_headers,
                        'body': response_body,
                        'is_binary': is_binary,
                        'content_type': content_type
                    }
                }

                self.captured_requests.append(captured)

                # Выводим информацию о запросе
                short_url = self._shorten_url(request.url)
                print(f"📥 {request.method} {short_url} ({response.status})" +
                      (" [BINARY]" if is_binary else ""))

            except Exception as e:
                print(f"❌ Ошибка перехвата: {e}")
                import traceback
                traceback.print_exc()

        self.page.on('response', intercept_response)

    def _shorten_url(self, url, max_length=80):
        """Сокращает URL для вывода"""
        if len(url) <= max_length:
            return url
        return url[:max_length - 3] + "..."

    async def _save_to_file(self):
        """Сохраняет записи в файл"""
        if not self.captured_requests:
            print("❌ Нет записанных запросов")
            return

        filename = f"api_calls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.captured_requests, f, indent=2, ensure_ascii=False)
            print(f"💾 Сохранено {len(self.captured_requests)} запросов в {filename}")

            # Показываем краткую информацию
            print(f"\nЗаписанные запросы:")
            for i, req in enumerate(self.captured_requests, 1):
                short_url = self._shorten_url(req['url'], 60)
                binary_mark = " [BINARY]" if req['response'].get('is_binary') else ""
                print(f"  {i}. {req['method']} {short_url} ({req['response']['status']}){binary_mark}")

        except Exception as e:
            print(f"❌ Ошибка при сохранении: {e}")


async def main():
    """Основная функция"""
    print("🎥 Simple API Recorder")
    print("Запись по умолчанию: ВЫКЛЮЧЕНА")
    print("Для начала записи введите команду: start")

    # Простой парсинг аргументов
    url = None
    if len(sys.argv) > 1:
        url = sys.argv[1]

    recorder = SimpleAPIRecorder()

    try:
        await recorder.start(url)
    except KeyboardInterrupt:
        print("\n🛑 Программа завершена")


if __name__ == "__main__":
    asyncio.run(main())