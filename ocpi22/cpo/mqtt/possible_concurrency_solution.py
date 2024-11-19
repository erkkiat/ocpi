import asyncio
import aioredis
import aiohttp
import orjson

# Dictionary to hold semaphores per receiver
semaphores = {}
# Lock to protect access to the semaphores dictionary
semaphores_lock = asyncio.Lock()


async def get_semaphore(receiver, max_concurrency):
    """Get or create a semaphore for a receiver with a given max_concurrency."""
    async with semaphores_lock:
        if receiver in semaphores:
            # Update semaphore if max_concurrency has changed
            semaphore_info = semaphores[receiver]
            if semaphore_info['max_concurrency'] != max_concurrency:
                # Log the change
                print(
                    f"Updating max_concurrency for receiver '{receiver}' from {semaphore_info['max_concurrency']} to {max_concurrency}")
                # Create a new semaphore with the new max_concurrency
                semaphore_info['semaphore'] = asyncio.Semaphore(max_concurrency)
                semaphore_info['max_concurrency'] = max_concurrency
        else:
            # Create a new semaphore for this receiver
            semaphores[receiver] = {
                'semaphore': asyncio.Semaphore(max_concurrency),
                'max_concurrency': max_concurrency
            }
    return semaphores[receiver]['semaphore']


async def handle_item(a):
    receiver = a['receiver']
    max_concurrency = a['max_concurrency']
    url = a['url']
    payload = a['data']

    semaphore = await get_semaphore(receiver, max_concurrency)

    async with semaphore:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    status = response.status
                    await response.text()
                    print(f"Sent data to {url}, status: {status}")
                    # Optionally process the response_text
        except Exception as e:
            print(f"Error sending data to {url}: {e}")


async def process_queue():
    redis = await aioredis.create_redis_pool('redis://localhost')

    try:
        while True:
            # BLPOP to block until an item is available in the queue 'my_queue'
            key, data = await redis.blpop('my_queue')

            # Deserialize the data using orjson
            a = orjson.loads(data)

            # Schedule the handling of the item as a task
            asyncio.create_task(handle_item(a))

    except Exception as e:
        print(f"Error processing queue item: {e}")
    finally:
        redis.close()
        await redis.wait_closed()


if __name__ == '__main__':
    asyncio.run(process_queue())
