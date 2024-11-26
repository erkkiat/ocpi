import json

import aiohttp
import asyncio


async def post_request(session, url, data, headers=None):
    headers = headers or {}
    headers.update({"Content-Type": "application/json", "Accept:": "application/json"})
    async with session.get(url, json=data, headers=headers) as response:
        status = response.status
        try:
            # json_data = await response.content.read()
            json_data = await response.json()
            # if len(json_data) < 1000:
            # json_data = json.loads(json_data.decode('utf-8'))
        except (aiohttp.ContentTypeError, json.JSONDecodeError):
            # Handle the case where response is not JSON or cannot be decoded
            print("Cannot decode JSON response")
            json_data = None

        return status, json_data


def process_task_result(successful_task):
    print(
        f"Response from {successful_task.get_name()} len: {len(successful_task.result())}"
    )
    try:
        status_code, json_data = successful_task.result()
        if isinstance(json_data, dict):
            json_data = json_data.get("data")
            # If content is a Token authorize response, then break, otherwise continue
            if isinstance(json_data, dict) and json_data.get("allowed"):
                print(f"Received authorization from {successful_task.get_name()}")
                return json_data
    except (aiohttp.ContentTypeError, json.JSONDecodeError):
        # Handle the case where response is not JSON or cannot be decoded
        print("Cannot decode JSON response")
        pass
    return None


async def authorize_with_all_msps(url_list: list[tuple[str, str]]):
    data = {"key": "value"}  # Replace with your actual POST data
    result = None

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(post_request(session, url, data), name=name)
            for url, name in url_list
        ]

        while tasks:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            print(
                f"Processing {len(done)} done tasks ({len(pending)} still pending)..."
            )

            for task in done:
                try:
                    status, data = task.result()
                    if status == 200:
                        result = process_task_result(task)
                        if result:
                            break
                    else:
                        print(
                            f"Task {task.get_name()} failed with return code {status}"
                        )
                except Exception as e:
                    print(f"Task {task.get_name()} raised an exception:", e)

            if not pending:
                # No more tasks pending, break the loop
                print("No successful tasks.")
                return None

            tasks = set(pending)

        # Cancel all pending tasks as we have found our successful task or there are no tasks left
        for task in pending:
            print(f"Cancelling task {task.get_name()}", task.cancel())

        return result


if __name__ == "__main__":
    urls = [
        (
            "https://chargerhub.proxy.beeceptor.com/ocpi/token/EKI1/authorize",
            "beeceptor",
        ),
        # ('https://novacharge.ocpiconnector.com/ocpi/token/EKI1/authorize', 'novacharge'),
        ("http://localhost:8000/ocpi/2.2.1/tokens/EKI1/authorize", "local MSP"),
        ("https://cpo-ocpi.herokuapp.com/ocpi/versions/", "cpo-ocpi"),
        # ('https://ocpiguide.com/jeejee/', 'ocpiguide'),
        # ('https://solidroam.com/nonexistent/', 'nonexistent'),
    ]

    response = asyncio.run(authorize_with_all_msps(urls))
    print(f"Result: {response=}")
