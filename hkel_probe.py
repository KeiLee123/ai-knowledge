#!/usr/bin/env python3

import json
import urllib.request


MASTER_URL = (
    "https://resource.data.one.gov.hk/doj/data/"
    "hkel_list_c_all_en.json"
)


def fetch_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Jason-AI-Knowledge/1.0"
        }
    )

    with urllib.request.urlopen(
        req,
        timeout=60
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def walk(obj, path="$"):
    if isinstance(obj, dict):
        yield path, obj

        for key, value in obj.items():
            yield from walk(
                value,
                f"{path}.{key}"
            )

    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from walk(
                value,
                f"{path}[{i}]"
            )


def main():

    data = fetch_json(MASTER_URL)

    print("=" * 72)
    print("HKeL CURRENT LEGISLATION MANIFEST")
    print("=" * 72)

    if isinstance(data, dict):
        print("Top-level keys:")
        for key in data:
            print(" -", key)

    print()

    chapter_hits = []

    for path, item in walk(data):
        if not isinstance(item, dict):
            continue

        values = {
            str(v).strip()
            for v in item.values()
            if isinstance(v, (str, int))
        }

        if "572" in values:
            chapter_hits.append(
                (path, item)
            )

    print(
        "Objects containing value '572':",
        len(chapter_hits)
    )

    for path, item in chapter_hits[:5]:
        print()
        print("PATH:", path)
        print(
            json.dumps(
                item,
                indent=2,
                ensure_ascii=False
            )[:5000]
        )

    print()
    print("JSON resource URLs discovered:")
    print()

    urls = []

    for _, item in walk(data):
        if not isinstance(item, dict):
            continue

        for value in item.values():
            if (
                isinstance(value, str)
                and value.startswith("http")
                and ".json" in value.lower()
            ):
                urls.append(value)

    for url in sorted(set(urls))[:30]:
        print(url)

    print()
    print("Total JSON resource URLs:", len(set(urls)))


if __name__ == "__main__":
    main()
