"""
Простой парсер mitmproxy файлов в JSON
Использование: python mitm_to_json.py файл.mitm
"""

import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from mitmproxy import io as mitm_io
from mitmproxy.http import HTTPFlow


def parse_mitm_file(file_path: str) -> List[Dict[str, Any]]:
    """Парсит файл mitmproxy и возвращает список транзакций в JSON-совместимом формате"""
    transactions = []

    if not Path(file_path).exists():
        print(f"Ошибка: файл '{file_path}' не найден")
        return []

    print(f"Парсинг файла: {file_path}")

    with open(file_path, "rb") as f:
        try:
            flow_reader = mitm_io.FlowReader(f)

            for i, flow in enumerate(flow_reader.stream()):
                if not isinstance(flow, HTTPFlow):
                    continue

                # Формируем информацию о запросе
                request_info = {
                    "method": flow.request.method,
                    "url": flow.request.pretty_url,
                    "path": flow.request.path,
                    "http_version": flow.request.http_version,
                    "headers": dict(flow.request.headers),
                    "timestamp": flow.request.timestamp_start,
                    "timestamp_iso": datetime.fromtimestamp(flow.request.timestamp_start).isoformat()
                    if hasattr(flow.request, 'timestamp_start') else None
                }

                # Добавляем тело запроса
                if flow.request.raw_content:
                    try:
                        # Пробуем декодировать как текст
                        request_info["body_text"] = flow.request.raw_content.decode('utf-8', errors='replace')
                    except:
                        # Если не текстовое, кодируем в base64
                        request_info["body_base64"] = base64.b64encode(flow.request.raw_content).decode('ascii')
                    request_info["body_size"] = len(flow.request.raw_content)

                # Формируем информацию об ответе
                response_info = None
                if flow.response:
                    response_info = {
                        "status_code": flow.response.status_code,
                        "reason": flow.response.reason,
                        "http_version": flow.response.http_version,
                        "headers": dict(flow.response.headers),
                        "timestamp": flow.response.timestamp_end if hasattr(flow.response, 'timestamp_end') else None,
                        "timestamp_iso": datetime.fromtimestamp(flow.response.timestamp_end).isoformat()
                        if hasattr(flow.response, 'timestamp_end') else None
                    }

                    # Добавляем тело ответа
                    if flow.response.raw_content:
                        try:
                            response_info["body_text"] = flow.response.raw_content.decode('utf-8', errors='replace')
                        except:
                            response_info["body_base64"] = base64.b64encode(flow.response.raw_content).decode('ascii')
                        response_info["body_size"] = len(flow.response.raw_content)

                # Формируем полную транзакцию
                transaction = {
                    "id": f"flow_{i:06d}",
                    "request": request_info,
                    "response": response_info,
                    "duration": flow.response.timestamp_end - flow.request.timestamp_start
                    if flow.response and hasattr(flow.response, 'timestamp_end') else None
                }

                transactions.append(transaction)

                # Прогресс
                if (i + 1) % 10 == 0:
                    print(f"  Обработано {i + 1} транзакций...")

            print(f"Успешно обработано {len(transactions)} транзакций")

        except EOFError:
            print(f"Обработано {len(transactions)} транзакций (достигнут конец файла)")
        except Exception as e:
            print(f"Ошибка при чтении файла: {e}")

    return transactions


def save_to_json(transactions: List[Dict[str, Any]], input_file_path: str) -> str:
    """Сохраняет транзакции в JSON файл"""
    input_path = Path(input_file_path)
    output_path = input_path.with_suffix('.json')

    # Если файл уже существует, добавляем индекс
    counter = 1
    while output_path.exists():
        output_path = input_path.with_name(f"{input_path.stem}_{counter}.json")
        counter += 1

    result = {
        "metadata": {
            "source_file": str(input_path.name),
            "generated_at": datetime.now().isoformat(),
            "total_transactions": len(transactions)
        },
        "transactions": transactions
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    return str(output_path)


def main():
    if len(sys.argv) != 2:
        print("Использование: python mitm_to_json.py <файл.mitm>")
        print("Пример: python mitm_to_json.py flows.mitm")
        sys.exit(1)

    input_file = sys.argv[1]

    # Парсим файл
    transactions = parse_mitm_file(input_file)

    if not transactions:
        print("Не удалось извлечь транзакции из файла")
        sys.exit(1)

    # Сохраняем в JSON
    output_file = save_to_json(transactions, input_file)

    print(f"\n✅ Результат сохранён в: {output_file}")
    print(f"   Всего транзакций: {len(transactions)}")
    print(f"   Размер JSON: {Path(output_file).stat().st_size} байт")


if __name__ == "__main__":
    main()
