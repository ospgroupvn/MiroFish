"""
Bộ sinh thông minh cấu hình mô phỏng
Sử dụng LLM tự động sinh tham số mô phỏng chi tiết dựa trên yêu cầu mô phỏng, nội dung tài liệu, thông tin đồ thị
Triển khai tự động hoàn toàn, không cần thiết lập tham số thủ công

Áp dụng chiến lược sinh từng bước, tránh sinh nội dung quá dài một lần dẫn đến thất bại:
1. Sinh cấu hình thời gian
2. Sinh cấu hình sự kiện
3. Sinh cấu hình Agent theo lô
4. Sinh cấu hình nền tảng
"""

import json
import math
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.simulation_config')

# Cấu hình thời gian sinh hoạt Trung Quốc (giờ Bắc Kinh)
CHINA_TIMEZONE_CONFIG = {
    # Khung giờ đêm khuya (hầu như không ai hoạt động)
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # Khung giờ sáng sớm (dần thức giấc)
    "morning_hours": [6, 7, 8],
    # Khung giờ làm việc
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # Khung giờ cao điểm buổi tối (hoạt động mạnh nhất)
    "peak_hours": [19, 20, 21, 22],
    # Khung giờ đêm (hoạt động giảm)
    "night_hours": [23],
    # Hệ số hoạt động
    "activity_multipliers": {
        "dead": 0.05,      # Sáng sớm hầu như không ai
        "morning": 0.4,    # Sáng sớm dần hoạt động
        "work": 0.7,       # Khung giờ làm việc trung bình
        "peak": 1.5,       # Cao điểm buổi tối
        "night": 0.5       # Đêm khuya giảm
    }
}


@dataclass
class AgentActivityConfig:
    """Cấu hình hoạt động cho một Agent"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # Cấu hình mức độ hoạt động (0.0-1.0)
    activity_level: float = 0.5  # Mức độ hoạt động tổng thể
    
    # Tần suất phát ngôn (số lần phát ngôn dự kiến mỗi giờ)
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0
    
    # Khung giờ hoạt động (24 giờ, 0-23)
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    
    # Tốc độ phản hồi (độ trễ phản ứng với sự kiện nóng, đơn vị: phút mô phỏng)
    response_delay_min: int = 5
    response_delay_max: int = 60
    
    # Khuynh hướng cảm xúc (-1.0 đến 1.0, tiêu cực đến tích cực)
    sentiment_bias: float = 0.0
    
    # Lập trường (thái độ với chủ đề cụ thể)
    stance: str = "neutral"  # supportive, opposing, neutral, observer
    
    # Trọng số ảnh hưởng (quyết định xác suất phát ngôn được Agent khác nhìn thấy)
    influence_weight: float = 1.0


@dataclass  
class TimeSimulationConfig:
    """Cấu hình mô phỏng thời gian (dựa trên thói quen sinh hoạt người Trung Quốc)"""
    # Tổng thời gian mô phỏng (số giờ mô phỏng)
    total_simulation_hours: int = 72  # Mặc định mô phỏng 72 giờ (3 ngày)
    
    # Thời gian mỗi vòng (phút mô phỏng) - mặc định 60 phút (1 giờ), tăng tốc dòng thời gian
    minutes_per_round: int = 60
    
    # Phạm vi số Agent kích hoạt mỗi giờ
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20
    
    # Khung giờ cao điểm (19-22 giờ tối, thời gian người Trung Quốc hoạt động mạnh nhất)
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5
    
    # Khung giờ thấp điểm (0-5 giờ sáng, hầu như không ai hoạt động)
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # Sáng sớm hoạt động cực thấp
    
    # Khung giờ sáng sớm
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4
    
    # Khung giờ làm việc
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """Cấu hình sự kiện"""
    # Sự kiện ban đầu (sự kiện kích hoạt khi bắt đầu mô phỏng)
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)
    
    # Sự kiện định kỳ (sự kiện kích hoạt ở thời điểm cụ thể)
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # Từ khóa chủ đề nóng
    hot_topics: List[str] = field(default_factory=list)
    
    # Hướng dẫn dư luận
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """Cấu hình đặc thù nền tảng"""
    platform: str  # twitter or reddit
    
    # Trọng số thuật toán đề xuất
    recency_weight: float = 0.4  # Độ tươi thời gian
    popularity_weight: float = 0.3  # Độ nóng
    relevance_weight: float = 0.3  # Độ tương quan
    
    # Ngưỡng lan truyền virus (đạt bao nhiêu tương tác thì kích hoạt lan tỏa)
    viral_threshold: int = 10
    
    # Cường độ hiệu ứng buồng vang (mức độ tập trung quan điểm tương đồng)
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """Cấu hình tham số mô phỏng đầy đủ"""
    # Thông tin cơ bản
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str
    
    # Cấu hình thời gian
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    
    # Danh sách cấu hình Agent
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    
    # Cấu hình sự kiện
    event_config: EventConfig = field(default_factory=EventConfig)
    
    # Cấu hình nền tảng
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None
    
    # Cấu hình LLM
    llm_model: str = ""
    llm_base_url: str = ""
    
    # Siêu dữ liệu sinh
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # Giải thích suy luận của LLM
    
    def to_dict(self) -> Dict[str, Any]:
        """Chuyển sang từ điển"""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Chuyển sang chuỗi JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    Bộ sinh thông minh cấu hình mô phỏng
    
    Sử dụng LLM phân tích yêu cầu mô phỏng, nội dung tài liệu, thông tin entity đồ thị,
    Tự động sinh cấu hình tham số mô phỏng tối ưu
    
    Áp dụng chiến lược sinh từng bước:
    1. Sinh cấu hình thời gian và sự kiện (nhẹ)
    2. Sinh cấu hình Agent theo lô (mỗi lô 10-20 cái)
    3. Sinh cấu hình nền tảng
    """
    
    # Số ký tự tối đa ngữ cảnh
    MAX_CONTEXT_LENGTH = 50000
    # Số Agent sinh mỗi lô
    AGENTS_PER_BATCH = 15
    
    # Độ dài cắt ngữ cảnh các bước (số ký tự)
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # Cấu hình thời gian
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # Cấu hình sự kiện
    ENTITY_SUMMARY_LENGTH = 300          # Tóm tắt entity
    AGENT_SUMMARY_LENGTH = 300           # Tóm tắt entity trong cấu hình Agent
    ENTITIES_PER_TYPE_DISPLAY = 20       # Số lượng hiển thị mỗi loại entity
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY chưa được cấu hình")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        Sinh thông minh cấu hình mô phỏng đầy đủ (sinh từng bước)
        
        Args:
            simulation_id: ID mô phỏng
            project_id: ID dự án
            graph_id: ID đồ thị
            simulation_requirement: Mô tả yêu cầu mô phỏng
            document_text: Nội dung tài liệu gốc
            entities: Danh sách entity đã lọc
            enable_twitter: Có bật Twitter không
            enable_reddit: Có bật Reddit không
            progress_callback: Hàm callback tiến độ (current_step, total_steps, message)
            
        Returns:
            SimulationParameters: Tham số mô phỏng đầy đủ
        """
        logger.info(f"Bắt đầu sinh thông minh cấu hình mô phỏng: simulation_id={simulation_id}, số entity={len(entities)}")
        
        # Tính tổng số bước
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # Cấu hình thời gian + Cấu hình sự kiện + N lô Agent + Cấu hình nền tảng
        current_step = 0
        
        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")
        
        # 1. Xây dựng thông tin ngữ cảnh cơ bản
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )
        
        reasoning_parts = []
        
        # ========== Bước 1: Sinh cấu hình thời gian ==========
        report_progress(1, t('progress.generatingTimeConfig'))
        logger.info("Bước 1/3: Đang sinh cấu hình thời gian...")
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"{t('progress.timeConfigLabel')}: {time_config_result.get('reasoning', t('common.success'))}")
        
        # ========== Bước 2: Sinh cấu hình sự kiện ==========
        report_progress(2, t('progress.generatingEventConfig'))
        logger.info("Bước 2/3: Đang sinhCấu hình sự kiện...")
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"{t('progress.eventConfigLabel')}: {event_config_result.get('reasoning', t('common.success'))}")
        
        # ========== Bước 3-N: Sinh cấu hình Agent theo lô ==========
        logger.info(f"Bước 3/3: Đang sinh cấu hình Agent theo lô, tổng {num_batches} lô, mỗi lô {self.AGENTS_PER_BATCH} Agent...")
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]
            
            report_progress(
                3 + batch_idx,
                t('progress.generatingAgentConfig', start=start_idx + 1, end=end_idx, total=len(entities))
            )
            logger.info(f"  Lô {batch_idx + 1}/{num_batches}: Sinh Agent {start_idx + 1}-{end_idx} cấu hình...")

            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)
        
        reasoning_parts.append(t('progress.agentConfigResult', count=len(all_agent_configs)))
        
        # ========== Phân bổ Agent phát hành cho bài đăng ban đầu ==========
        logger.info("Phân bổ Agent phát hành phù hợp cho bài đăng ban đầu...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(t('progress.postAssignResult', count=assigned_count))
        
        # ========== Bước cuối: Sinh cấu hình nền tảng ==========
        report_progress(total_steps, t('progress.generatingPlatformConfig'))
        logger.info("Bước cuối: Đang sinh cấu hình nền tảng...")
        twitter_config = None
        reddit_config = None
        
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )
        
        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )
        
        # Xây dựng tham số cuối cùng
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )

        logger.info(f"Sinh cấu hình mô phỏng hoàn thành: {len(params.agent_configs)} cấu hình Agent")
        logger.info(f"  ├─ Cấu hình thời gian: {params.time_config.total_simulation_hours}giờ, {params.time_config.minutes_per_round}phút/vòng")
        logger.info(f"  ├─ Cấu hình sự kiện: {len(params.event_config.initial_posts)}bài đăng ban đầu, {len(params.event_config.hot_topics)}chủ đề nóng")
        logger.info(f"  ├─ Cấu hình nền tảng: Twitter={'✓' if params.twitter_config else '✗'}, Reddit={'✓' if params.reddit_config else '✗'}")

        return params
    
    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """Xây dựng ngữ cảnh LLM, cắt đến độ dài tối đa"""
        
        # Tóm tắt entity
        entity_summary = self._summarize_entities(entities)
        
        # Xây dựng ngữ cảnh
        context_parts = [
            f"## Yêu cầu mô phỏng\n{simulation_requirement}",
            f"\n## Thông tin entity ({len(entities)}cái)\n{entity_summary}",
        ]
        
        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # Để dư 500 ký tự
        
        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(Tài liệu đã bị cắt)"
            context_parts.append(f"\n## Nội dung tài liệu gốc\n{doc_text}")
        
        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """Sinh tóm tắt entity"""
        lines = []
        
        # Nhóm theo loại
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)}cái)")
            # Sử dụng số lượng hiển thị và độ dài tóm tắt đã cấu hình
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... còn {len(type_entities) - display_count} cái")
        
        return "\n".join(lines)
    
    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """Gọi LLM có retry, bao gồm logic sửa JSON"""
        import re

        max_attempts = 3
        last_error = None

        logger.info(f"Bắt đầu gọi LLM sinh cấu hình...")

        for attempt in range(max_attempts):
            try:
                logger.info(f"  LLM call attempt {attempt + 1}/{max_attempts}...")
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # Mỗi lần retry giảm nhiệt độ
                    # Không đặt max_tokens, để LLM tự do phát huy
                )
                
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                logger.info(f"  ✓ LLM response received (finish_reason={finish_reason})")

                # Kiểm tra có bị cắt không
                if finish_reason == 'length':
                    logger.warning(f"Đầu ra LLM bị cắt (lần thử {attempt+1})")
                    content = self._fix_truncated_json(content)
                
                # Thử phân tích JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Phân tích JSON thất bại (lần thử {attempt+1}): {str(e)[:80]}")
                    
                    # Thử sửa JSON
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed
                    
                    last_error = e
                    
            except Exception as e:
                logger.warning(f"Gọi LLM thất bại (lần thử {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))
        
        raise last_error or Exception("Gọi LLM thất bại")
    
    def _fix_truncated_json(self, content: str) -> str:
        """Sửa JSON bị cắt"""
        content = content.strip()
        
        # Tính số ngoặc chưa đóng
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # Kiểm tra có chuỗi chưa đóng không
        if content and content[-1] not in '",}]':
            content += '"'
        
        # Đóng ngoặc
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Thử sửa JSON cấu hình"""
        import re
        
        # Sửa trường hợp bị cắt
        content = self._fix_truncated_json(content)
        
        # Trích xuất phần JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # Xóa ký tự xuống dòng trong chuỗi
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except:
                # Thử xóa tất cả ký tự điều khiển
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """Sinh cấu hình thời gian"""
        # Sử dụng độ dài cắt ngữ cảnh đã cấu hình
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        
        # Tính giá trị tối đa cho phép (80% số agent)
        max_agents_allowed = max(1, int(num_entities * 0.9))
        
        prompt = f"""Dựa trên yêu cầu mô phỏng sau, sinh cấu hình mô phỏng thời gian.

{context_truncated}

## Nhiệm vụ
Hãy sinh cấu hình thời gian dưới dạng JSON.

### Nguyên tắc cơ bản (chỉ để tham khảo, cần linh hoạt điều chỉnh theo sự kiện và nhóm tham gia cụ thể):
- Vui lòng suy luận múi giờ và thói quen sinh hoạt của nhóm người dùng mục tiêu theo kịch bản mô phỏng, dưới đây là ví dụ tham khảo cho múi giờ Đông Tám (UTC+8)
- Khung giờ đêm khuya 0-5 giờ hầu như không ai hoạt động (Hệ số hoạt động 0.05)
- Khung giờ sáng sớm 6-8 giờ dần thức giấc (Hệ số hoạt động 0.4)
- Khung giờ làm việc 9-18 giờ hoạt động trung bình (Hệ số hoạt động 0.7)
- Khung giờ cao điểm buổi tối 19-22 giờ (Hệ số hoạt động 1.5)
- Sau 23 giờ hoạt động giảm (Hệ số hoạt động 0.5)
- Quy luật chung: Đêm khuya hoạt động thấp, sáng sớm tăng dần, Khung giờ làm việc trung bình, Cao điểm buổi tối
- **Quan trọng**: Các giá trị ví dụ sau chỉ để tham khảo, bạn cần điều chỉnh khung giờ cụ thể theo tính chất sự kiện, đặc điểm nhóm tham gia
  - Ví dụ: nhóm sinh viên cao điểm có thể là 21-23 giờ; truyền thông hoạt động cả ngày; cơ quan chính thức chỉ trong giờ làm
  - Ví dụ: điểm nóng đột phát có thể khiến đêm khuya cũng có thảo luận, off_peak_hours có thể rút ngắn phù hợp

### Trả về định dạng JSON (không markdown)

Ví dụ:
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "Giải thích cấu hình thời gian cho sự kiện này"
}}

Giải thích trường:
- total_simulation_hours (int): Tổng thời gian mô phỏng, 24-168 giờ, sự kiện đột phát ngắn, chủ đề kéo dài lâu
- minutes_per_round (int): Thời gian mỗi vòng, 30-120 phút, khuyến nghị 60 phút
- agents_per_hour_min (int): Số Agent kích hoạt tối thiểu mỗi giờ (phạm vi: 1-{max_agents_allowed})
- agents_per_hour_max (int): Số Agent kích hoạt tối đa mỗi giờ (phạm vi: 1-{max_agents_allowed})
- peak_hours (mảng int): Khung giờ cao điểm, điều chỉnh theo nhóm tham gia sự kiện
- off_peak_hours (mảng int): Khung giờ thấp điểm, thường đêm khuya sáng sớm
- morning_hours (mảng int): Khung giờ sáng sớm
- work_hours (mảng int): Khung giờ làm việc
- reasoning (string): Giải thích ngắn gọn tại sao cấu hình như vậy"""

        system_prompt = "Bạn là chuyên gia mô phỏng mạng xã hội. Trả về định dạng JSON thuần, cấu hình thời gian phải phù hợp với thói quen sinh hoạt của nhóm người dùng mục tiêu trong kịch bản mô phỏng."
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Sinh cấu hình thời gian LLM thất bại: {e}, Sử dụng cấu hình mặc định")
            return self._get_default_time_config(num_entities)
    
    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """Lấy cấu hình thời gian mặc định (sinh hoạt người Trung Quốc)"""
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # Mỗi vòng 1 giờ, tăng tốc dòng thời gian
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Sử dụng cấu hình sinh hoạt người Trung Quốc mặc định (mỗi vòng 1 giờ)"
        }
    
    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """Phân tích kết quả cấu hình thời gian, kiểm tra giá trị agents_per_hour không vượt quá tổng số agent"""
        # Lấy giá trị gốc
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))
        
        # Kiểm tra và sửa: Đảm bảo không vượt quá tổng số agent
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) vượt quá tổng số Agent ({num_entities})，đã sửa")
            agents_per_hour_min = max(1, num_entities // 10)
        
        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) vượt quá tổng số Agent ({num_entities})，đã sửa")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
        
        # Đảm bảo min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max，đã sửa thành {agents_per_hour_min}")
        
        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # Mặc định mỗi vòng 1 giờ
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # Sáng sớm hầu như không ai
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )
    
    def _generate_event_config(
        self, 
        context: str, 
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """Sinh cấu hình sự kiện"""
        
        # Lấy danh sách loại entity khả dụng, để LLM tham khảo
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))
        
        # Liệt kê tên entity đại diện cho mỗi loại
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)
        
        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}" 
            for t, examples in type_examples.items()
        ])
        
        # Sử dụng độ dài cắt ngữ cảnh đã cấu hình
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]
        
        prompt = f"""Dựa trên yêu cầu mô phỏng sau, sinh cấu hình sự kiện.

Yêu cầu mô phỏng: {simulation_requirement}

{context_truncated}

## Loại entity khả dụng và ví dụ
{type_info}

## Nhiệm vụ
Hãy sinh cấu hình sự kiện dưới dạng JSON:
- Trích xuất từ khóa chủ đề nóng
- Mô tả hướng phát triển dư luận
- Thiết kế nội dung bài đăng ban đầu, **mỗi bài phải chỉ định poster_type (loại người phát)**

**Quan trọng**: poster_type phải chọn từ "loại entity khả dụng" ở trên, như vậy bài đăng ban đầu mới có thể phân bổ cho Agent phù hợp phát hành.
Ví dụ: Tuyên bố chính thức nên do loại Official/University phát, tin tức do MediaOutlet phát, quan điểm sinh viên do Student phát.

Trả về định dạng JSON (không markdown)：
{{
    "hot_topics": ["từ khóa1", "từ khóa2", ...],
    "narrative_direction": "<mô tả hướng phát triển dư luận>",
    "initial_posts": [
        {{"content": "nội dung bài đăng", "poster_type": "loại entity (phải chọn từ loại khả dụng)"}},
        ...
    ],
    "reasoning": "<giải thích ngắn gọn>"
}}"""

        system_prompt = "Bạn là chuyên gia phân tích dư luận. Trả về định dạng JSON thuần. Lưu ý poster_type phải khớp chính xác với các loại entity khả dụng."
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'poster_type' field value MUST be in English PascalCase exactly matching the available entity types. Only 'content', 'narrative_direction', 'hot_topics' and 'reasoning' fields should use the specified language."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Sinh cấu hình sự kiện LLM thất bại: {e}, Sử dụng cấu hình mặc định")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "Sử dụng cấu hình mặc định"
            }
    
    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """Phân tích kết quả cấu hình sự kiện"""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )
    
    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        Phân bổ Agent phát hành phù hợp cho bài đăng ban đầu
        
        Khớp agent_id phù hợp nhất theo poster_type của mỗi bài
        """
        if not event_config.initial_posts:
            return event_config
        
        # Thiết lập chỉ mục agent theo loại entity
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)
        
        # Bảng ánh xạ loại (xử lý các định dạng khác nhau LLM có thể xuất)
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }
        
        # Ghi lại chỉ mục agent đã dùng cho mỗi loại, tránh dùng trùng một agent
        used_indices: Dict[str, int] = {}
        
        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")
            
            # Thử tìm agent khớp
            matched_agent_id = None
            
            # 1. Khớp trực tiếp
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. Dùng bí danh khớp
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break
            
            # 3. Nếu vẫn không tìm thấy, dùng agent có ảnh hưởng cao nhất
            if matched_agent_id is None:
                logger.warning(f"Không tìm thấy loại '{poster_type}' Agent khớp, dùng Agent có ảnh hưởng cao nhất")
                if agent_configs:
                    # Sắp xếp theo ảnh hưởng, chọn cái có ảnh hưởng cao nhất
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0
            
            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })
            
            logger.info(f"Phân bổ bài đăng ban đầu: poster_type='{poster_type}' -> agent_id={matched_agent_id}")
        
        event_config.initial_posts = updated_posts
        return event_config
    
    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """Sinh cấu hình Agent theo lô"""
        
        # Xây dựng thông tin entity (sử dụng độ dài tóm tắt đã cấu hình)
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })
        
        prompt = f"""Dựa trên thông tin sau, sinh cấu hình hoạt động mạng xã hội cho mỗi entity.

Yêu cầu mô phỏng: {simulation_requirement}

## Danh sách entity
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## Nhiệm vụ
Sinh cấu hình hoạt động cho mỗi entity, chú ý:
- **Thời gian phù hợp sinh hoạt nhóm người dùng mục tiêu**: Dưới đây là tham khảo (Đông bát khu), vui lòng điều chỉnh theo kịch bản mô phỏng
- **Cơ quan chính thức** (University/GovernmentAgency): Hoạt động thấp(0.1-0.3), hoạt động giờ làm(9-17), phản hồi chậm(60-240 phút), ảnh hưởng cao(2.5-3.0)
- **Truyền thông** (MediaOutlet): Hoạt động trung bình(0.4-0.6), hoạt động cả ngày(8-23), phản hồi nhanh(5-30 phút), ảnh hưởng cao(2.0-2.5)
- **Cá nhân** (Student/Person/Alumni): Hoạt động cao(0.6-0.9), chủ yếu hoạt động buổi tối(18-23), phản hồi nhanh(1-15 phút), ảnh hưởng thấp(0.8-1.2)
- **Nhân vật công chúng/Chuyên gia**: Hoạt động trung bình(0.4-0.6), ảnh hưởng trung cao(1.5-2.0)

Trả về định dạng JSON (không markdown)：
{{
    "agent_configs": [
        {{
            "agent_id": <phải nhất quán với đầu vào>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <tần suất đăng bài>,
            "comments_per_hour": <tần suất bình luận>,
            "active_hours": [<danh sách giờ hoạt động, xem xét sinh hoạt người Trung Quốc>],
            "response_delay_min": <phút trễ phản hồi tối thiểu>,
            "response_delay_max": <phút trễ phản hồi tối đa>,
            "sentiment_bias": <-1.0 đến 1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <trọng số ảnh hưởng>
        }},
        ...
    ]
}}"""

        system_prompt = "Bạn là chuyên gia phân tích hành vi mạng xã hội. Trả về JSON thuần, cấu hình phải phù hợp với thói quen sinh hoạt của nhóm người dùng mục tiêu trong kịch bản mô phỏng."
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'stance' field value MUST be one of the English strings: 'supportive', 'opposing', 'neutral', 'observer'. All JSON field names and numeric values must remain unchanged. Only natural language text fields should use the specified language."

        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Sinh cấu hình Agent theo lô LLM thất bại: {e}, Sinh theo quy tắc")
            llm_configs = {}
        
        # Xây dựng đối tượng AgentActivityConfig
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})
            
            # Nếu LLM không sinh, sinh theo quy tắc
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)
            
            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0)
            )
            configs.append(config)
        
        return configs
    
    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """Sinh cấu hình Agent đơn theo quy tắc (sinh hoạt người Trung Quốc)"""
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        
        if entity_type in ["university", "governmentagency", "ngo"]:
            # Cơ quan chính thức: Hoạt động giờ làm, tần suất thấp, ảnh hưởng cao
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Truyền thông: Hoạt động cả ngày, tần suất trung bình, ảnh hưởng cao
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Chuyên gia/Giáo sư: Hoạt động làm+buổi tối, tần suất trung bình
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Sinh viên: Chủ yếu buổi tối, tần suất cao
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Sáng+buổi tối
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Cựu sinh viên: Chủ yếu buổi tối
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # Nghỉ trưa+buổi tối
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # Người thường: Cao điểm buổi tối
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Ban ngày+buổi tối
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
    

