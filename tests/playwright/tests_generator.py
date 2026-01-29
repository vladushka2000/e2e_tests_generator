import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Any
from urllib.parse import unquote


class APITestGenerator:
    def __init__(self, json_file_path: str):
        """
        Инициализация генератора тестов

        Args:
            json_file_path: Путь к JSON-файлу с логами
        """
        self.json_file_path = json_file_path
        self.api_logs = []
        self.endpoint_tests = {}  # Группировка по эндпоинтам и параметрам

    def load_json_data(self):
        """Загрузка и парсинг JSON данных"""
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                self.api_logs = json.load(f)
            print(f"Загружено {len(self.api_logs)} записей из {self.json_file_path}")
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

    def extract_api_info(self, log_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Извлечение информации об API запросе из лога"""
        try:
            url = log_entry.get('url', '')
            method = log_entry.get('method', 'GET')
            response_body = log_entry.get('response', {}).get('body', '{}')
            response_status = log_entry.get('response', {}).get('status', 200)

            # Извлекаем эндпоинт из URL
            endpoint_match = re.search(r'(?:https?://[^/]+)?(/api/.*?)(?:\?|$)', url)
            if endpoint_match:
                endpoint = endpoint_match.group(1)
            else:
                # Пытаемся найти путь без домена
                if url.startswith('/'):
                    endpoint = url.split('?')[0]
                else:
                    endpoint = '/' + url.split('/api/')[-1] if '/api/' in url else url

            # Извлекаем параметры запроса и сразу парсим значения
            params = {}
            if '?' in url:
                query_string = url.split('?')[1]
                params = self.parse_query_params(query_string)

            # Парсим тело ответа - json.loads сам заменит null на None, true/false на True/False
            try:
                response_data = json.loads(response_body)
            except:
                response_data = {}

            return {
                'endpoint': endpoint,
                'method': method,
                'url': url,
                'params': params,
                'response_data': response_data,
                'response_status': response_status,
                'timestamp': log_entry.get('timestamp', ''),
            }
        except Exception as e:
            print(f"Ошибка при обработке записи лога: {e}")
            return {}

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
        """Группировка логов по эндпоинтам и параметрам"""
        for log in self.api_logs:
            api_info = self.extract_api_info(log)
            if not api_info:
                continue

            endpoint = api_info['endpoint']
            method = api_info['method']
            params = api_info['params']

            # Создаем ключ для группировки: эндпоинт + отсортированные параметры
            params_key = tuple(sorted(params.items()))
            group_key = (endpoint, method, params_key)

            if group_key not in self.endpoint_tests:
                self.endpoint_tests[group_key] = {
                    'endpoint': endpoint,
                    'method': method,
                    'params': params,
                    'samples': [],
                }

            self.endpoint_tests[group_key]['samples'].append(api_info)

        print(f"Обнаружено {len(self.endpoint_tests)} уникальных комбинаций эндпоинт+параметры")

    def create_test_function_name(self, endpoint: str, method: str, params: Dict) -> str:
        """Создание имени тестовой функции с учетом параметров"""
        # Извлекаем последнюю часть эндпоинта
        parts = endpoint.strip('/').split('/')
        if parts:
            func_name = parts[-1] if parts[-1] else parts[-2] if len(parts) > 1 else "endpoint"
        else:
            func_name = "endpoint"

        # Добавляем основные параметры к имени функции
        param_suffix = ""
        important_params = ['search', 'current_page', 'limit', 'status', 'start_date', 'end_date',
                            'page_size', 'time_type', 'pool_type', 'is_rejected']

        for param_name in important_params:
            if param_name in params and params[param_name] is not None and params[param_name] != "":
                param_value = str(params[param_name])
                # Ограничиваем длину значения
                if len(param_value) > 20:
                    param_value = param_value[:10] + "..."
                # Заменяем недопустимые символы
                param_value = re.sub(r'[^a-zA-Z0-9_]', '_', param_value)
                param_suffix += f"_{param_name}_{param_value}"

        # Если есть другие параметры, добавляем общее указание
        if len(params) > 0 and not param_suffix:
            param_suffix = "_with_params"

        # Преобразуем в snake_case
        func_name = re.sub(r'[^a-zA-Z0-9]', '_', func_name + param_suffix).lower()
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
            # Генерируем строку в зависимости от типа значения
            if isinstance(value, str):
                # Строковое значение
                escaped_value = value.replace('"', '\\"')
                line = f'            "{key}": "{escaped_value}"'
            elif value is None:
                # None значение
                line = f'            "{key}": None'
            elif isinstance(value, bool):
                # Булево значение
                line = f'            "{key}": {value}'
            elif isinstance(value, (int, float)):
                # Числовое значение
                line = f'            "{key}": {value}'
            else:
                # Другие типы - преобразуем в строку
                line = f'            "{key}": {repr(value)}'

            # Добавляем запятую только если это не последний элемент
            if i < len(param_items) - 1:
                line += ','

            params_lines.append(line)

        params_str = "\n".join(params_lines)
        return f"params={{\n{params_str}\n        }}"

    def generate_expected_data(self, sample: Dict[str, Any]) -> str:
        """Генерация строки с ожидаемыми данными, где None представлен как None в Python"""
        response_data = sample['response_data']

        # Используем pprint для форматирования Python-объекта
        import pprint
        formatted = pprint.pformat(response_data, indent=1, width=100, depth=None)

        # Убираем первый пробел отступа (indent=1 дает один пробел)
        lines = formatted.split('\n')
        lines = [line[1:] if line.startswith(' ') else line for line in lines]

        return '\n'.join(lines)

    def generate_test_function(self, test_data: Dict[str, Any]) -> str:
        """Генерация тестовой функции для эндпоинта"""
        endpoint = test_data['endpoint']
        method = test_data['method']
        params = test_data['params']
        sample = test_data['samples'][0]  # Используем первый образец

        func_name = self.create_test_function_name(endpoint, method, params)

        # Создаем ожидаемый результат с None вместо null
        expected_data = self.generate_expected_data(sample)

        # Формируем URL пути (без параметров)
        url_path = endpoint

        # Генерируем строку с параметрами
        params_str = self.generate_params_dict(params)

        # Формируем тестовую функцию
        test_function = f'''@pytest.mark.asyncio
async def {func_name}(
        fast_api_client,
):
    expected = {expected_data}

    response = await fast_api_client.{method.lower()}(
        "{url_path}"'''

        if params_str:
            test_function += f",\n        {params_str}"

        test_function += ''',
    )

    assert response.status_code == HTTPStatus.OK
    assert json.loads(response.content.decode()) == expected

'''
        return test_function

    def organize_tests_by_resource(self) -> Dict[str, List]:
        """Организация тестов по ресурсам (группировка эндпоинтов с одного ресурса)"""
        resource_tests = {}

        for group_key, test_data in self.endpoint_tests.items():
            endpoint = test_data['endpoint']

            # Определяем ресурс - извлекаем основную часть пути после версии API
            parts = endpoint.strip('/').split('/')

            if len(parts) >= 3:
                # Начинаем с 2-го элемента (после 'api' и версии)
                for i in range(2, len(parts)):
                    resource_candidate = parts[i]
                    # Ищем значимую часть (не 'api', не версию, не слишком общие слова)
                    if (resource_candidate and
                            resource_candidate not in ['api', 'v1', 'v2', 'v3', 'v4', 'v5'] and
                            resource_candidate not in ['workspace', 'new_operplan', 'perspective_plan']):
                        resource = resource_candidate
                        break
                else:
                    # Если не нашли значимую часть, используем последнюю
                    resource = parts[-1] if parts[-1] else parts[-2]
            elif len(parts) == 2:
                resource = parts[1]
            else:
                resource = 'other'

            # Нормализуем имя ресурса
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
            # Создаем папку для каждого ресурса
            resource_dir = current_dir / resource
            resource_dir.mkdir(exist_ok=True)
            test_dirs[resource] = resource_dir

        return test_dirs

    def save_test_file(self, resource: str, tests: List[Dict[str, Any]], resource_dir: Path):
        """Сохранение тестового файла для ресурса в соответствующую папку"""
        # Создаем имя файла - test_<ресурс>.py или просто test.py если имя слишком длинное
        if len(resource) > 30:
            file_name = "test.py"
        else:
            file_name = f"test_{resource}.py"

        # Генерируем содержимое файла
        imports = self.generate_test_imports()

        # Сортируем тесты для более предсказуемого порядка
        tests_sorted = sorted(tests, key=lambda x: (
            x['endpoint'],
            tuple(sorted(x['params'].items()))
        ))

        # Генерируем все тестовые функции
        test_functions = []
        for test_data in tests_sorted:
            test_func = self.generate_test_function(test_data)
            test_functions.append(test_func)

        file_content = imports + "\n\n".join(test_functions)

        # Сохраняем файл в папке ресурса
        file_path = resource_dir / file_name
        file_path.write_text(file_content, encoding='utf-8')
        print(f"Создан тестовый файл: {file_path}")

        return file_path

    def run(self):
        """Основной метод запуска генерации тестов"""
        print("=" * 60)
        print("Генератор тестов API из JSON логов")
        print("=" * 60)

        # Загружаем данные
        self.load_json_data()

        # Группируем по эндпоинтам и параметрам
        self.group_by_endpoint_and_params()

        if not self.endpoint_tests:
            print("Не найдено данных для генерации тестов")
            return

        # Организуем тесты по ресурсам
        resource_tests = self.organize_tests_by_resource()
        print(f"Обнаружено {len(resource_tests)} различных ресурсов:")
        for resource in resource_tests.keys():
            print(f"  - {resource} ({len(resource_tests[resource])} тестов)")

        # Создаем структуру папок
        test_dirs = self.create_directory_structure(resource_tests)

        # Генерируем тестовые файлы
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

    parser = argparse.ArgumentParser(description='Генератор тестов API из JSON логов')
    parser.add_argument('json_file', help='Путь к JSON файлу с логами API')

    args = parser.parse_args()

    if not os.path.exists(args.json_file):
        print(f"Ошибка: файл {args.json_file} не найден!")
        sys.exit(1)

    generator = APITestGenerator(args.json_file)
    generator.run()


if __name__ == "__main__":
    main()
