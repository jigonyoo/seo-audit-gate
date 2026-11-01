"""Local Apify file layout, with SDK imports confined to platform execution."""
import json
import os
from pathlib import Path


class LocalStorage:
    def __init__(self, root='storage'):
        self.root = Path(root)
        self.charges = []
        self.sequence = 0

    async def get_input(self):
        return json.loads((self.root / 'key_value_stores/default/INPUT.json').read_text(encoding='utf-8'))

    async def push_data(self, item):
        folder = self.root / 'datasets/default'
        folder.mkdir(parents=True, exist_ok=True)
        self.sequence = max(self.sequence, max((int(p.stem) for p in folder.glob('*.json')
                                              if p.stem.isdigit()), default=0)) + 1
        (folder / f'{self.sequence:09d}.json').write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')

    async def set_value(self, key, value, content_type):
        folder = self.root / 'key_value_stores/default'
        folder.mkdir(parents=True, exist_ok=True)
        extension = 'json' if content_type == 'application/json' else 'md'
        text = json.dumps(value, ensure_ascii=False, indent=2) if extension == 'json' else value
        (folder / f'{key}.{extension}').write_text(text, encoding='utf-8')

    async def charge(self, event_name):
        # Local runs record intent only; no monetary charges are submitted.
        self.charges.append(event_name)


class PlatformStorage:
    def __init__(self, actor):
        self.actor = actor

    async def get_input(self):
        return await self.actor.get_input()

    async def push_data(self, item):
        await self.actor.push_data(item)

    async def set_value(self, key, value, content_type):
        # With explicit content_type the SDK receives serialized record content.
        content = json.dumps(value, ensure_ascii=False) if content_type == 'application/json' else value
        await self.actor.set_value(key, content, content_type=content_type)

    async def charge(self, event_name):
        result = await self.actor.charge(event_name=event_name, count=1)
        if result is not None and getattr(result, 'event_charge_limit_reached', False):
            raise RuntimeError('page-audited charge limit reached')


async def main():
    from actor import run
    if os.environ.get('APIFY_IS_AT_HOME') == '1':
        from apify import Actor
        async with Actor:
            storage = PlatformStorage(Actor)
            await run(await storage.get_input(), storage)
    else:
        storage = LocalStorage()
        await run(await storage.get_input(), storage)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
