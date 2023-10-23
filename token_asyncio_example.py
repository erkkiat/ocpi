import aiohttp
import asyncio


async def post_request(session, url, data):
    async with session.post(url, json=data) as response:
        status_code = response.status  # Get the HTTP status code
        print(f"URL {url}: status code {status_code}")
        return await response.json()


async def main():
    urls = [
        'https://cpo-ocpi.herokuapp.com/ocpi/versions/',
        'https://ocpiguide.com/',
        'https://solidroam.com/nonexistent/'
    ]  # Replace with your actual URLs

    data = {'key': 'value'}  # Replace with your actual POST data

    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(post_request(session, url, data), name=url) for url in urls]
        # tasks_to_urls = {task: url for task, url in zip(tasks, urls)}
        # Todo: We can't use the first completed if it's not status code 200
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=28)

        # Cancel all pending tasks
        for task in pending:
            task.cancel()

        # Process completed tasks
        for task in done:
            try:
                # url = tasks_to_urls[task]
                print(f"Completed task URL {task.get_name()} result len: {len(task.result())}")
            except Exception as e:
                print("First completed task raised an exception:", e)

        if not len(done):
            print("No task finished during the timeout.")
if __name__ == '__main__':
    asyncio.run(main())
