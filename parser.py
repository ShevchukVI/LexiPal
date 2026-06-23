import os
import csv
import boto3
from botocore.exceptions import ClientError


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=os.getenv('S3_ENDPOINT_URL'),
        aws_access_key_id=os.getenv('S3_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('S3_SECRET_ACCESS_KEY'),
        region_name='us-east-1'  # Як у тебе на скріні
    )


def parse_cloudflare_obsidian():
    """Сканує файли .md прямо в хмарі Cloudflare R2"""
    s3 = get_s3_client()
    bucket = os.getenv('S3_BUCKET_NAME')
    cards = []

    try:
        # Отримуємо список всіх файлів у хмарі
        response = s3.list_objects_v2(Bucket=bucket)
        if 'Contents' not in response:
            return []

        for obj in response['Contents']:
            key = obj['Key']
            # Шукаємо тільки markdown файли
            if key.endswith('.md'):
                # Читаємо файл прямо в пам'ять
                file_obj = s3.get_object(Bucket=bucket, Key=key)
                content = file_obj['Body'].read().decode('utf-8')

                # Шукаємо наші слова через ::
                for line in content.split('\n'):
                    if '::' in line:
                        parts = line.split('::')
                        if len(parts) == 2:
                            front = parts[0].strip()
                            back = parts[1].strip()
                            if front and back:
                                cards.append({"front": front, "back": back})
        return cards
    except ClientError as e:
        print(f"Помилка підключення до Cloudflare: {e}")
        return []


def parse_local_csv(filepath="extra_words.csv"):
    """Читає додаткові слова з CSV файлу"""
    cards = []
    if not os.path.exists(filepath):
        return cards

    with open(filepath, mode='r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) == 2:
                cards.append({"front": row[0].strip(), "back": row[1].strip()})
    return cards