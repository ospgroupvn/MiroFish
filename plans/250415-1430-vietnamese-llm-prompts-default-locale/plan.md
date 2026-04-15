---
title: Vietnamese LLM Prompts & Default Locale
description: Translate all LLM system prompts to Vietnamese and set vi as default locale
status: pending
createdAt: 2025-04-15T14:30:00Z
---

# Vietnamese LLM Prompts & Default Locale

## Overview
- **Priority**: High
- **Status**: Pending
- **Description**: Translate all LLM system prompts from Chinese to Vietnamese and set Vietnamese as the default locale for the MiroFish application.

## Scope
This plan covers:
1. Setting Vietnamese as default locale (frontend + backend)
2. Translating all LLM system prompts to Vietnamese
3. Keeping technical constraints (field names, enums) in English
4. Testing to ensure LLM outputs are in Vietnamese

## Files to Modify

| File | Changes |
|------|---------|
| `locales/languages.json` | Mark Vietnamese as default |
| `backend/app/utils/locale.py` | Change fallback locale from 'en' to 'vi' |
| `frontend/src/i18n/index.js` | Change default locale from 'en' to 'vi' |
| `backend/app/services/ontology_generator.py` | Translate `ONTOLOGY_SYSTEM_PROMPT` to Vietnamese |
| `backend/app/services/report_agent.py` | Translate `PLAN_SYSTEM_PROMPT`, `SECTION_SYSTEM_PROMPT_TEMPLATE`, `CHAT_SYSTEM_PROMPT_TEMPLATE` to Vietnamese |
| `backend/app/services/simulation_config_generator.py` | Translate time/event/agent config prompts to Vietnamese |
| `backend/app/services/zep_tools.py` | Translate interview prompts to Vietnamese |

## Implementation Phases

### Phase 1: Set Default Locale
- Update locale fallback to 'vi' in backend (`locale.py`)
- Update default locale to 'vi' in frontend (`i18n/index.js`)
- Verify `Accept-Language` header defaults to 'vi'

### Phase 2: Translate Ontology Generator Prompts
- Translate `ONTOLOGY_SYSTEM_PROMPT` in `ontology_generator.py` to Vietnamese
- Keep English constraints for field names (PascalCase, snake_case, UPPER_SNAKE_CASE)
- Test ontology generation produces Vietnamese output

### Phase 3: Translate Report Agent Prompts
- Translate `PLAN_SYSTEM_PROMPT` in `report_agent.py` to Vietnamese
- Translate `SECTION_SYSTEM_PROMPT_TEMPLATE` to Vietnamese
- Translate `CHAT_SYSTEM_PROMPT_TEMPLATE` to Vietnamese
- Keep tool names and technical terms in English

### Phase 4: Translate Simulation Config Prompts
- Translate time configuration prompts in `simulation_config_generator.py`
- Translate event configuration prompts
- Translate agent activity configuration prompts
- Keep enum values in English ('supportive', 'opposing', etc.)

### Phase 5: Translate Interview Prompts
- Translate agent selection prompts in `zep_tools.py`
- Translate interview question generation prompts
- Translate interview summary prompts
- Translate interview response instructions

### Phase 6: Testing & Validation
- Test full simulation flow with Vietnamese locale
- Verify all LLM outputs are in Vietnamese
- Verify technical fields remain in English
- Test frontend displays Vietnamese UI correctly

## Success Criteria
- ✅ All LLM prompts are in Vietnamese
- ✅ Default locale is Vietnamese (no need to manually select)
- ✅ LLM outputs (reports, ontologies, configs, interviews) are in Vietnamese
- ✅ Technical field names and enums remain in English
- ✅ Frontend builds successfully
- ✅ Full simulation flow works end-to-end with Vietnamese

## Risks & Mitigation
| Risk | Mitigation |
|------|------------|
| LLM may not understand Vietnamese prompts well | Use clear, formal Vietnamese; test with multiple models |
| Translation may break prompt structure | Keep prompt structure identical, only translate natural language |
| Hardcoded Chinese cultural references | Generalize or adapt to Vietnamese context where appropriate |
