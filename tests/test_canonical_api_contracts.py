"""The published API is one typed, discoverable client contract."""
import asyncio
import json

from fastapi.testclient import TestClient

from scripts.export_api_contracts import contracts
from src import server
from src.backend.api_contracts import ActionPlanStreamEvent, ChatStreamEvent
from src.services.action_plan_jobs import ActionPlanJobService
from src.services.automation_catalog import OPERATIONS


def test_all_business_routes_and_catalog_operations_use_one_namespace():
    paths = server.app.openapi()['paths']
    assert paths
    assert all(path.startswith('/api/v1/') for path in paths)
    assert all(not op.path or op.path.startswith('/api/v1/') for op in OPERATIONS)
    assert not {'action_plan.generate', 'action_plan.content.read'} & {op.name for op in OPERATIONS}
    client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))
    for old in ['/api/status', '/api/action_plan', '/api/action_plan_content', '/api/automation/settings']:
        assert client.get(old).status_code == 404
    assert not hasattr(server, 'get_today_action_plan')
    assert not hasattr(server, 'generate_action_plan')


def test_core_response_and_request_dtos_are_exposed_in_openapi():
    schema = server.app.openapi()
    for path, method, model in [
        ('/api/v1/settings', 'get', 'SettingsState'),
        ('/api/v1/onboarding', 'get', 'OnboardingState'),
        ('/api/v1/onboarding/complete', 'post', 'OnboardingCompletion'),
        ('/api/v1/chat/context', 'get', 'ChatContextResponse'),
        ('/api/v1/action-plan/scheduler', 'get', 'SchedulerState'),
    ]:
        assert schema['paths'][path][method]['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/'+model)
    for method in ('get', 'delete'):
        assert schema['paths']['/api/v1/chat/context'][method]['responses']['503']['content']['application/json']['schema']['$ref'].endswith('/ContextErrorResponse')
    request = schema['paths']['/api/v1/settings']['put']['requestBody']['content']['application/json']['schema']
    assert request['properties']['voice_api_key']['writeOnly'] is True
    assert 'provider_config' in request['properties'] and 'provider' not in request['properties']
    exported = contracts()['schemas']
    assert {'SettingsUpdateRequest', 'OnboardingCompleteRequest', 'ChatRequest', 'ChatContextResponse',
            'SchedulerState', 'ChatStreamEvent', 'ActionPlanStreamEvent'} <= set(exported)


def test_ndjson_wire_media_type_and_per_record_union_are_correct():
    schema = server.app.openapi()
    for path, method, model in [('/api/v1/chat', 'post', 'ChatStreamEvent'),
                                 ('/api/v1/action-plan/jobs/{job_id}/events', 'get', 'ActionPlanStreamEvent')]:
        content = schema['paths'][path][method]['responses']['200']['content']
        assert set(content) == {'application/x-ndjson'}
        assert content['application/x-ndjson']['x-ndjson-item-schema']['$ref'].endswith('/'+model)
        assert 'anyOf' in schema['components']['schemas'][model]
    ChatStreamEvent.model_validate({'log': 'progress'})
    ChatStreamEvent.model_validate({'done': True})


def test_actual_job_event_records_validate_against_exported_union():
    async def exercise():
        saved = {'exists': False}
        async def generate(_request):
            yield {'log': 'progress'}
            saved.update(exists=True, id='new', analysis={'body': 'a'}, plan={'body': 'b'})
            yield {'done': True}
        service = ActionPlanJobService(generate, lambda: dict(saved))
        job = await service.start()
        await service.wait(job['id'])
        for item in service.events(job['id'])['events']:
            ActionPlanStreamEvent.model_validate_json(json.dumps(item))
        await service.close()
    asyncio.run(exercise())
