import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from urllib.parse import unquote, urlparse


class APITestGenerator:
    def __init__(self, json_file_path: str):
        """
        Инициализация генератора тестов

        Args:
            json_file_path: Путь к JSON-файлу с логами
        """
        self.json_file_path = json_file_path
        self.data = {}
        self.transactions = []
        self.endpoint_tests = {}  # Группировка по эндпоинтам и параметрам

    def load_json_data(self):
        """Загрузка и парсинг JSON данных"""
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)

            self.transactions = self.data.get('transactions', [])
            print(f"Загружено {len(self.transactions)} транзакций из {self.json_file_path}")
            print(f"Метаданные: {self.data.get('metadata', {})}")

        except Exception as e:
            print(f"Ошибка при загрузке JSON: {e}")
            sys.exit(1)

    def parse_value(self, value: str) -> Any:
        """Парсинг строкового значения в Python-тип"""
        if value == "":
            return ""
        elif value.lower() == "null":
            return None
        elif value.lower() == "true":
            return True
        elif value.lower() == "false":
            return False
        elif value.isdigit():
            # Целое число
            return int(value)
        elif value.replace('.', '', 1).isdigit() and value.count('.') == 1:
            # Вещественное число
            return float(value)
        else:
            # Строка - возвращаем как есть
            return value

    def extract_file_info(self, request_body_text: str) -> Optional[Dict[str, Any]]:
        """Извлечение информации о файле из multipart/form-data"""
        if not request_body_text or 'multipart/form-data' not in request_body_text:
            return None

        try:
            # Ищем boundary
            boundary_match = re.search(r'boundary=([^\s;]+)', request_body_text)
            if not boundary_match:
                return None

            boundary = boundary_match.group(1)
            parts = request_body_text.split(f'--{boundary}')

            for part in parts:
                if 'filename=' in part:
                    # Извлекаем информацию о файле
                    filename_match = re.search(r'filename="([^"]+)"', part)
                    content_type_match = re.search(r'Content-Type: ([^\r\n]+)', part)
                    name_match = re.search(r'name="([^"]+)"', part)

                    if filename_match:
                        filename = filename_match.group(1)
                        content_type = content_type_match.group(1) if content_type_match else 'application/octet-stream'
                        field_name = name_match.group(1) if name_match else 'file'

                        # Извлекаем бинарные данные файла
                        header_end = part.find('\r\n\r\n')
                        if header_end != -1:
                            file_data_start = header_end + 4
                            file_data = part[file_data_start:]

                            if file_data.endswith('\r\n'):
                                file_data = file_data[:-2]

                            is_binary = any(ord(c) < 32 and c not in '\r\n\t' for c in file_data[:100])

                            if is_binary:
                                file_data_base64 = base64.b64encode(file_data.encode('latin-1')).decode('utf-8')
                                return {
                                    'field_name': field_name,
                                    'filename': filename,
                                    'content_type': content_type,
                                    'is_binary': True,
                                    'data_base64': file_data_base64,
                                    'size': len(file_data)
                                }
                            else:
                                return {
                                    'field_name': field_name,
                                    'filename': filename,
                                    'content_type': content_type,
                                    'is_binary': False,
                                    'data_text': file_data,
                                    'size': len(file_data)
                                }

        except Exception as e:
            print(f"Ошибка при парсинге файла: {e}")

        return None

    def extract_request_body(self, request: Dict[str, Any]) -> Optional[Any]:
        """Извлечение и парсинг тела запроса"""
        request_body_text = request.get('body_text', '')
        content_type = request.get('headers', {}).get('Content-Type', '')

        if not request_body_text:
            return None

        # Пытаемся распарсить как JSON
        if 'application/json' in content_type:
            try:
                return json.loads(request_body_text)
            except:
                # Если не парсится как JSON, возвращаем как строку
                return request_body_text

        # Для multipart/form-data возвращаем информацию о файле
        elif 'multipart/form-data' in content_type:
            return self.extract_file_info(request_body_text)

        # Для других типов возвращаем как есть
        else:
            return request_body_text

    def extract_api_info(self, transaction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Извлечение информации об API запросе из транзакции"""
        try:
            request = transaction.get('request', {})
            response = transaction.get('response', {})

            url = request.get('url', '')
            method = request.get('method', 'GET')
            response_body_text = response.get('body_text', '{}')
            response_status = response.get('status_code', 200)
            response_headers = response.get('headers', {})

            # Извлекаем эндпоинт из URL
            parsed_url = urlparse(url)
            endpoint = parsed_url.path

            # Извлекаем параметры запроса
            params = {}
            if parsed_url.query:
                params = self.parse_query_params(parsed_url.query)

            # Извлекаем тело запроса
            request_body = self.extract_request_body(request)

            # Парсим тело ответа
            response_data = {}
            response_is_file = False
            response_filename = None

            # Проверяем, является ли ответ файлом
            content_disposition = response_headers.get('content-disposition', '')
            if 'attachment' in content_disposition:
                response_is_file = True
                filename_match = re.search(r'filename="([^"]+)"', content_disposition)
                response_filename = filename_match.group(1) if filename_match else 'downloaded_file'

            # Если это файл, сохраняем текст как есть
            if response_is_file:
                response_data = response_body_text
            else:
                # Пытаемся распарсить как JSON
                try:
                    if response_body_text.strip():
                        response_data = json.loads(response_body_text)
                except:
                    response_data = response_body_text

            return {
                'endpoint': endpoint,
                'method': method,
                'url': url,
                'params': params,
                'request_body': request_body,
                'response_data': response_data,
                'response_status': response_status,
                'response_is_file': response_is_file,
                'response_filename': response_filename,
                'response_content_type': response_headers.get('content-type', ''),
                'timestamp': request.get('timestamp_iso', ''),
            }
        except Exception as e:
            print(f"Ошибка при обработке транзакции {transaction.get('id', 'unknown')}: {e}")
            return None

    def parse_query_params(self, query_string: str) -> Dict[str, Any]:
        """Парсинг query параметров с декодированием URL и преобразованием типов"""
        params = {}
        try:
            for param in query_string.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    # Декодируем URL-encoded значения
                    key = unquote(key)
                    value = unquote(value)
                    # Парсим значение в Python-тип
                    params[key] = self.parse_value(value)
        except:
            pass
        return params

    def group_by_endpoint_and_params(self):
        """Группировка транзакций по эндпоинтам и параметрам"""
        for transaction in self.transactions:
            api_info = self.extract_api_info(transaction)
            if not api_info:
                continue

            endpoint = api_info['endpoint']
            method = api_info['method']
            params = api_info['params']
            request_body = api_info['request_body']

            # Создаем ключ для группировки
            params_key = tuple(sorted(params.items()))
            body_key = None
            if request_body:
                if isinstance(request_body, dict) and 'field_name' in request_body:
                    # Для файлов используем информацию о файле
                    body_key = ('file', request_body.get('field_name'), request_body.get('filename'))
                elif isinstance(request_body, dict):
                    # Для JSON используем хэш словаря
                    body_key = ('json', json.dumps(request_body, sort_keys=True))
                else:
                    # Для других типов используем строковое представление
                    body_key = ('other', str(request_body))

            group_key = (endpoint, method, params_key, body_key)

            if group_key not in self.endpoint_tests:
                self.endpoint_tests[group_key] = {
                    'endpoint': endpoint,
                    'method': method,
                    'params': params,
                    'request_body': request_body,
                    'samples': [],
                }

            self.endpoint_tests[group_key]['samples'].append(api_info)

        print(f"Обнаружено {len(self.endpoint_tests)} уникальных комбинаций эндпоинт+параметры")

    def create_test_function_name(self, endpoint: str, method: str, params: Dict,
                                  request_body: Optional[Any] = None) -> str:
        """Создание имени тестовой функции с учетом параметров"""
        # Извлекаем последнюю часть эндпоинта
        parts = endpoint.strip('/').split('/')
        if parts:
            func_name = parts[-1] if parts[-1] else parts[-2] if len(parts) > 1 else "endpoint"
        else:
            func_name = "endpoint"

        # Добавляем информацию о запросе к имени функции
        body_suffix = ""
        if request_body:
            if isinstance(request_body, dict) and 'field_name' in request_body:
                # Для файлов
                filename = request_body.get('filename', 'file')
                filename_base = re.sub(r'\.[^.]+$', '', filename)
                filename_clean = re.sub(r'[^a-zA-Z0-9_]', '_', filename_base)
                body_suffix = f"_upload_{filename_clean}"
            elif isinstance(request_body, dict):
                # Для JSON - добавляем ключи
                keys = list(request_body.keys())
                if keys:
                    key_str = "_".join(keys[:2])  # Берем первые 2 ключа
                    body_suffix = f"_with_{key_str}"
                else:
                    body_suffix = "_with_body"

        # Добавляем основные параметры к имени функции
        param_suffix = ""
        important_params = ['search', 'current_page', 'limit', 'status', 'start_date', 'end_date',
                            'page_size', 'time_type', 'pool_type', 'is_rejected']

        for param_name in important_params:
            if param_name in params and params[param_name] is not None and params[param_name] != "":
                param_value = str(params[param_name])
                if len(param_value) > 20:
                    param_value = param_value[:10] + "..."
                param_value = re.sub(r'[^a-zA-Z0-9_]', '_', param_value)
                param_suffix += f"_{param_name}_{param_value}"

        if len(params) > 0 and not param_suffix:
            param_suffix = "_with_params"

        # Преобразуем в snake_case
        func_name = re.sub(r'[^a-zA-Z0-9]', '_', func_name + body_suffix + param_suffix).lower()
        func_name = re.sub(r'_+', '_', func_name)

        return f"test_{func_name}"

    def generate_test_imports(self) -> str:
        """Генерация импортов для тестового файла"""
        return '''import json
from http import HTTPStatus

import pytest

'''

    def generate_params_dict(self, params: Dict[str, Any]) -> str:
        """Генерация строки с параметрами для теста"""
        if not params:
            return ""

        params_lines = []
        param_items = list(params.items())

        for i, (key, value) in enumerate(param_items):
            if isinstance(value, str):
                escaped_value = value.replace('"', '\\"')
                line = f'            "{key}": "{escaped_value}"'
            elif value is None:
                line = f'            "{key}": None'
            elif isinstance(value, bool):
                line = f'            "{key}": {value}'
            elif isinstance(value, (int, float)):
                line = f'            "{key}": {value}'
            else:
                line = f'            "{key}": {repr(value)}'

            if i < len(param_items) - 1:
                line += ','

            params_lines.append(line)

        params_str = "\n".join(params_lines)
        return f"params={{\n{params_str}\n        }}"

    def generate_request_body_code(self, request_body: Any) -> str:
        """Генерация кода для тела запроса"""
        if request_body is None:
            return ""

        if isinstance(request_body, dict) and 'field_name' in request_body:
            # Для файлов
            return self.generate_file_upload_code(request_body)
        elif isinstance(request_body, dict):
            # Для JSON
            import pprint
            formatted = pprint.pformat(request_body, indent=1, width=100, depth=None)
            lines = formatted.split('\n')
            lines = [line[1:] if line.startswith(' ') else line for line in lines]
            json_data = '\n'.join(lines)

            return f'''json_data = {json_data}'''
        elif isinstance(request_body, str):
            # Для строковых данных
            escaped = request_body.replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
            return f'''data = "{escaped}"'''
        else:
            return ""

    def generate_file_upload_code(self, file_info: Dict[str, Any]) -> str:
        """Генерация кода для загрузки файла"""
        field_name = file_info.get('field_name', 'file')
        filename = file_info.get('filename', 'file')
        content_type = file_info.get('content_type', 'application/octet-stream')

        if file_info.get('is_binary', True):
            data_base64 = file_info.get('data_base64', '')
            return f'''
        # Подготовка файла для загрузки
        import io
        import base64
        file_data = base64.b64decode("{data_base64}")
        files = {{
            "{field_name}": ("{filename}", io.BytesIO(file_data), "{content_type}")
        }}'''
        else:
            data_text = file_info.get('data_text', '')
            escaped_text = data_text.replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
            return f'''
        # Подготовка файла для загрузки
        import io
        file_data = "{escaped_text}".encode('utf-8')
        files = {{
            "{field_name}": ("{filename}", io.BytesIO(file_data), "{content_type}")
        }}'''

    def generate_expected_data(self, sample: Dict[str, Any]) -> str:
        """Генерация строки с ожидаемыми данными"""
        response_data = sample['response_data']
        response_is_file = sample.get('response_is_file', False)

        if response_is_file:
            if isinstance(response_data, str):
                escaped_text = response_data.replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                return f'"{escaped_text}"'
            else:
                return repr(response_data)
        else:
            import pprint
            formatted = pprint.pformat(response_data, indent=1, width=100, depth=None)
            lines = formatted.split('\n')
            lines = [line[1:] if line.startswith(' ') else line for line in lines]
            return '\n'.join(lines)

    def generate_test_assertions(self, sample: Dict[str, Any]) -> str:
        """Генерация утверждений для теста"""
        response_is_file = sample.get('response_is_file', False)
        response_content_type = sample.get('response_content_type', '')
        response_filename = sample.get('response_filename', '')

        assertions = []
        assertions.append(f'    assert response.status_code == HTTPStatus.OK')

        if response_is_file:
            assertions.append(f'    # Проверка заголовков для файлового ответа')
            assertions.append(f'    assert "content-disposition" in response.headers')
            assertions.append(f'    assert "{response_filename}" in response.headers["content-disposition"]')

            if response_content_type:
                assertions.append(f'    assert response.headers["content-type"] == "{response_content_type}"')

            assertions.append(f'    expected_content = {self.generate_expected_data(sample)}')
            assertions.append(f'    assert response.content.decode("utf-8") == expected_content')
        else:
            assertions.append(f'    assert json.loads(response.content.decode()) == expected')

        return '\n'.join(assertions)

    def generate_test_function(self, test_data: Dict[str, Any]) -> str:
        """Генерация тестовой функции для эндпоинта"""
        endpoint = test_data['endpoint']
        method = test_data['method']
        params = test_data['params']
        request_body = test_data['request_body']
        sample = test_data['samples'][0]

        func_name = self.create_test_function_name(endpoint, method, params, request_body)
        expected_data = self.generate_expected_data(sample)
        url_path = endpoint
        params_str = self.generate_params_dict(params)

        # Формируем тестовую функцию
        test_function = f'''@pytest.mark.asyncio
async def {func_name}(
        fast_api_client,
):
    expected = {expected_data}

'''

        # Добавляем код для тела запроса
        body_code = self.generate_request_body_code(request_body)
        if body_code:
            test_function += f"    {body_code}"

        # Формируем вызов API
        if isinstance(request_body, dict) and 'field_name' in request_body:
            # Для файловых загрузок
            test_function += f'''

    response = await fast_api_client.{method.lower()}(
        "{url_path}"'''

            if params_str:
                test_function += f",\n        {params_str}"

            test_function += ''',
        files=files,
    )'''
        elif isinstance(request_body, dict):
            # Для JSON данных
            test_function += f'''

    response = await fast_api_client.{method.lower()}(
        "{url_path}"'''

            if params_str:
                test_function += f",\n        {params_str}"

            test_function += ''',
        json=json_data,
    )'''
        elif isinstance(request_body, str):
            # Для строковых данных
            test_function += f'''

    response = await fast_api_client.{method.lower()}(
        "{url_path}"'''

            if params_str:
                test_function += f",\n        {params_str}"

            test_function += ''',
        content=data,
    )'''
        else:
            # Для запросов без тела
            test_function += f'''
    response = await fast_api_client.{method.lower()}(
        "{url_path}"'''

            if params_str:
                test_function += f",\n        {params_str}"

            test_function += ''',
    )'''

        # Добавляем утверждения
        test_function += f'''

{self.generate_test_assertions(sample)}

'''
        return test_function

    def organize_tests_by_resource(self) -> Dict[str, List]:
        """Организация тестов по ресурсам"""
        resource_tests = {}

        for group_key, test_data in self.endpoint_tests.items():
            endpoint = test_data['endpoint']
            parts = endpoint.strip('/').split('/')

            if len(parts) >= 2:
                for i in range(len(parts)):
                    if parts[i] == 'api' and i + 1 < len(parts):
                        resource = parts[i + 1]
                        break
                else:
                    resource = parts[1] if len(parts) > 1 else parts[0]
            else:
                resource = 'other'

            resource = re.sub(r'[^a-zA-Z0-9]', '_', resource)
            if not resource:
                resource = 'unknown_resource'

            if resource not in resource_tests:
                resource_tests[resource] = []

            resource_tests[resource].append(test_data)

        return resource_tests

    def create_directory_structure(self, resource_tests: Dict[str, List]) -> Dict[str, Path]:
        """Создание структуры папок для тестов"""
        current_dir = Path.cwd()
        test_dirs = {}

        for resource in resource_tests.keys():
            resource_dir = current_dir / resource
            resource_dir.mkdir(exist_ok=True)
            test_dirs[resource] = resource_dir

        return test_dirs

    def save_test_file(self, resource: str, tests: List[Dict[str, Any]], resource_dir: Path):
        """Сохранение тестового файла"""
        if len(resource) > 30:
            file_name = "test.py"
        else:
            file_name = f"test_{resource}.py"

        imports = self.generate_test_imports()

        tests_sorted = sorted(tests, key=lambda x: (
            x['endpoint'],
            bool(x['request_body']),
            tuple(sorted(x['params'].items()))
        ))

        test_functions = []
        for test_data in tests_sorted:
            test_func = self.generate_test_function(test_data)
            test_functions.append(test_func)

        file_content = imports + "\n\n".join(test_functions)

        file_path = resource_dir / file_name
        file_path.write_text(file_content, encoding='utf-8')
        print(f"Создан тестовый файл: {file_path}")

        return file_path

    def run(self):
        """Основной метод запуска генерации тестов"""
        print("=" * 60)
        print("Генератор тестов API из JSON логов (с поддержкой тела запроса)")
        print("=" * 60)

        self.load_json_data()

        if not self.transactions:
            print("Не найдено транзакций в файле")
            return

        self.group_by_endpoint_and_params()

        if not self.endpoint_tests:
            print("Не найдено данных для генерации тестов")
            return

        file_uploads = sum(1 for test in self.endpoint_tests.values()
                           if isinstance(test.get('request_body'), dict) and 'field_name' in test['request_body'])
        json_requests = sum(1 for test in self.endpoint_tests.values()
                            if isinstance(test.get('request_body'), dict) and 'field_name' not in test['request_body'])

        print(f"Статистика:")
        print(f"  - Всего тестов: {len(self.endpoint_tests)}")
        print(f"  - С JSON телами запросов: {json_requests}")
        print(f"  - С загрузкой файлов: {file_uploads}")

        resource_tests = self.organize_tests_by_resource()
        print(f"\nОбнаружено {len(resource_tests)} различных ресурсов:")
        for resource, tests in resource_tests.items():
            json_count = sum(1 for test in tests
                             if isinstance(test.get('request_body'), dict) and 'field_name' not in test['request_body'])
            file_count = sum(1 for test in tests
                             if isinstance(test.get('request_body'), dict) and 'field_name' in test['request_body'])
            print(f"  - {resource} ({len(tests)} тестов, из них {json_count} JSON, {file_count} файлов)")

        test_dirs = self.create_directory_structure(resource_tests)

        generated_files = []
        for resource, tests in resource_tests.items():
            try:
                file_path = self.save_test_file(resource, tests, test_dirs[resource])
                generated_files.append(file_path)
            except Exception as e:
                print(f"Ошибка при генерации тестов для ресурса {resource}: {e}")

        print("\n" + "=" * 60)
        print("Генерация завершена успешно!")
        print(f"Создано {len(generated_files)} тестовых файлов в папках:")
        for file in generated_files:
            print(f"  - {file.parent.name}/{file.name}")
        print("=" * 60)


def main():
    """Основная функция"""
    import argparse

    parser = argparse.ArgumentParser(description='Генератор тестов API из JSON логов (с поддержкой тела запроса)')
    parser.add_argument('json_file', help='Путь к JSON файлу с логами API')

    args = parser.parse_args()

    if not os.path.exists(args.json_file):
        print(f"Ошибка: файл {args.json_file} не найден!")
        sys.exit(1)

    generator = APITestGenerator(args.json_file)
    generator.run()


if __name__ == "__main__":
    main()
