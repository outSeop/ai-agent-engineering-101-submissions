"""Lifecycle-only R4 endpoint: public identity plus an A2A maintenance refusal.

It loads public metadata only. There is no wallet, token, model, tool runner,
checkout, queue, ledger writer, payment or settlement path in this process.
"""
import argparse
import json
from pathlib import Path


def make_app(snapshot, url_file):
    from a2a.helpers import new_task_from_user_message, new_text_part
    from a2a.server.agent_execution import AgentExecutor
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    captured = json.loads(Path(snapshot).read_text())
    assert captured['name'] == 'outseop-r4'
    assert set(captured['wallets']) == {'shop'}
    notice = '현재 내부 점검 중입니다. 구매·견적·결제·정산을 받지 않습니다. 재개 전까지 송금하지 마세요.'
    skill = {'id': 'maintenance_notice', 'name': '점검 안내', 'description': notice,
             'tags': ['maintenance']}

    def card():
        url = Path(url_file).read_text().strip().rstrip('/')
        result = {'name': captured['name'], 'description': notice,
            'version': 'maintenance-1', 'skills': [skill], 'roles': ['shop'],
            'wallets': captured['wallets'], 'capabilities': {'streaming': False},
            'defaultInputModes': ['text/plain', 'application/json'],
            'defaultOutputModes': ['text/plain', 'application/json'],
            'supportedInterfaces': [{'url': url+'/', 'protocolBinding': 'JSONRPC',
                                     'protocolVersion': '1.0'}]}
        return result

    class Maintenance(AgentExecutor):
        async def execute(self, context, event_queue):
            task = context.current_task or new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
            updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
            message = updater.new_agent_message(parts=[new_text_part(notice)])
            await updater.reject(message)

        async def cancel(self, context, event_queue):
            task = context.current_task
            if task:
                await TaskUpdater(event_queue=event_queue, task_id=task.id,
                                  context_id=task.context_id).cancel()

    base_card = AgentCard(name='outseop-r4', description=notice, version='maintenance-1',
        capabilities=AgentCapabilities(streaming=False), default_input_modes=['text/plain'],
        default_output_modes=['text/plain'], skills=[AgentSkill(**skill)], supported_interfaces=[AgentInterface(
            protocol_binding='JSONRPC', url='http://127.0.0.1/', protocol_version='1.0')])
    handler = DefaultRequestHandler(agent_executor=Maintenance(), task_store=InMemoryTaskStore(),
                                    agent_card=base_card)

    async def get_card(_request):
        return JSONResponse(card())

    async def status(_request):
        return JSONResponse({'status': 'maintenance', 'trading_enabled': False,
                             'wallet_keys_loaded': False, 'tools_loaded': False})

    return Starlette(routes=[Route('/.well-known/agent-card.json', get_card), Route('/status', status)]
        + create_jsonrpc_routes(handler, '/', enable_v0_3_compat=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--url-file', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(make_app(args.snapshot, args.url_file), host='127.0.0.1', port=args.port,
                log_level='warning')


if __name__ == '__main__':
    main()
