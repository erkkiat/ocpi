import aiohttp
import asyncio


async def post_request(session, url, data):
    headers = {'Content-Type': 'application/json'}
    async with session.get(url, json=data, headers=headers) as response:
        status = response.status
        try:
            json_data = await response.json()
        except aiohttp.ContentTypeError:
            # Handle the case where response is not JSON or cannot be decoded
            json_data = None

        return status, json_data


async def main():
    urls = [
        'https://cpo-ocpi.herokuapp.com/ocpi/versions/',
        'https://ocpiguide.com/jeejee/',
        'https://solidroam.com/nonexistent/'
    ]  # Replace with your actual URLs

    data = {'key': 'value'}  # Replace with your actual POST data

    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(post_request(session, url, data), name=url) for url in urls]

        while tasks:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            successful_task = None
            for task in done:
                try:
                    status, data = task.result()
                    print(status, data)
                    if status == 200:
                        successful_task = task
                        break
                    else:
                        print(f'Task {task.get_name()} failed with return code {status}')
                except Exception as e:
                    print(f"Task {task.get_name()} raised an exception:", e)

            if successful_task:
                # Process the successful task
                print(f"Successful task URL {successful_task.get_name()} result len: {len(successful_task.result())}")
                break

            if not pending:
                # No more tasks pending, break the loop
                print("No successful tasks.")
                break

            tasks = set(pending)

        # Cancel all pending tasks as we have found our successful task or there are no tasks left
        for task in pending:
            task.cancel()


if __name__ == '__main__':
    asyncio.run(main())
