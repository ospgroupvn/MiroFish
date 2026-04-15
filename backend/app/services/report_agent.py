"""
Dịch vụ Report Agent
Sử dụng LangChain + Zep triển khai chế độ ReACT để sinh báo cáo mô phỏng

Chức năng:
1. Sinh báo cáo dựa trên yêu cầu mô phỏng và thông tin đồ thị Zep
2. Lên kế hoạch cấu trúc thư mục trước, sau đó sinh từng phần
3. Mỗi phần sử dụng chế độ suy nghĩ và phản ánh nhiều vòng ReACT
4. Hỗ trợ đối thoại với người dùng, tự chủ gọi công cụ tìm kiếm trong đối thoại
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Bộ ghi nhật ký chi tiết Report Agent
    
    Tạo file agent_log.jsonl trong thư mục báo cáo, ghi lại từng bước chi tiết.
    Mỗi dòng là một đối tượng JSON hoàn chỉnh, chứa timestamp, loại hành động, nội dung chi tiết, v.v.
    """
    
    def __init__(self, report_id: str):
        """
        Khởi tạo bộ ghi nhật ký
        
        Args:
            report_id: ID báo cáo, dùng để xác định đường dẫn file nhật ký
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Đảm bảo thư mục chứa file nhật ký tồn tại"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """Lấy thời gian đã trôi qua từ khi bắt đầu (giây)"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        Ghi một nhật ký
        
        Args:
            action: Loại hành động, như 'start', 'tool_call', 'llm_response', 'section_complete', v.v.
            stage: giai đoạn hiện tại, ví dụ 'planning', 'generating', 'completed'
            details: Từ điển nội dung chi tiết, không cắt ngắn
            section_title: Tiêu đề chương hiện tại (tùy chọn)
            section_index: Chỉ mục chương hiện tại (tùy chọn)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # Ghi vào file JSONL
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Ghi lại bắt đầu sinh báo cáo"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": t('report.taskStarted')
            }
        )
    
    def log_planning_start(self):
        """Ghi lại bắt đầu lên kế hoạch đề cương"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": t('report.planningStart')}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """Ghi lại thông tin ngữ cảnh lấy được khi lên kế hoạch"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": t('report.fetchSimContext'),
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """Ghi lại hoàn thành đề cương"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": t('report.planningComplete'),
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """Ghi lại bắt đầu sinh chương"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": t('report.sectionStart', title=section_title)}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """Ghi lại quá trình suy nghĩ ReACT"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": t('report.reactThought', iteration=iteration)
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """Ghi lại gọi công cụ"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": t('report.toolCall', toolName=tool_name)
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """Ghi lại gọi công cụ và kết quả (toàn bộ nội dung, không rút gọn)"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # Toàn bộ kết quả, không rút gọn
                "result_length": len(result),
                "message": t('report.toolResult', toolName=tool_name)
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """Ghi lại phản hồi LLM (nội dung đầy đủ, không cắt ngắn)"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # Toàn bộ phản hồi, không rút gọn
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": t('report.llmResponse', hasToolCalls=has_tool_calls, hasFinalAnswer=has_final_answer)
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """Ghi lại hoàn thành sinh nội dung chương (chỉ ghi nội dung, không đại diện cả chương hoàn thành)"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # Toàn bộ nội dung, không rút gọn
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": t('report.sectionContentDone', title=section_title)
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        Ghi lại hoàn thành sinh chương

        Frontend nên lắng nghe nhật ký này đểphán đoán một chương có thực sự hoàn thành không, và lấy nội dung đầy đủ
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": t('report.sectionComplete', title=section_title)
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """Ghi lại hoàn thành sinh báo cáo"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": t('report.reportComplete')
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """Ghi lại lỗi"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": t('report.errorOccurred', error=error_message)
            }
        )


class ReportConsoleLogger:
    """
    Bộ ghi nhật ký console Report Agent
    
    Ghi nhật ký kiểu console (INFO, WARNING, v.v.) vào file console_log.txt trong thư mục báo cáo.
    Những nhật ký này khác với agent_log.jsonl, là đầu ra console định dạng văn bản thuần.
    """
    
    def __init__(self, report_id: str):
        """
        Khởi tạo bộ ghi nhật ký console
        
        Args:
            report_id: ID báo cáo, dùng để xác định đường dẫn file nhật ký
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """Đảm bảo thư mục chứa file nhật ký tồn tại"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """Thiết lập file handler, đồng thời ghi nhật ký vào file"""
        import logging
        
        # Tạo file handler
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # Sử dụng định dạng ngắn gọn giống console
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # Thêm vào logger liên quan report_agent
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.zep_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # Tránh thêm trùng
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """Đóng file handler và xóa khỏi logger"""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """Đảm bảo đóng file handler khi hủy"""
        self.close()


class ReportStatus(str, Enum):
    """Trạng thái báo cáo"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """Chương báo cáo"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Chuyển sang định dạng Markdown"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """Đề cương báo cáo"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """Chuyển sang định dạng Markdown"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """Báo cáo đầy đủ"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Hằng số mẫu prompt
# ═══════════════════════════════════════════════════════════════

# ── Mô tả công cụ ──

TOOL_DESC_INSIGHT_FORGE = """\
[Tìm kiếminsight sâu - Công cụ tìm kiếm mạnh mẽ]
Đây là hàm tìm kiếm mạnh mẽ của chúng tôi, được thiết kế cho phân tích chuyên sâu. Nó sẽ:
1. Tự động chia nhỏ câu hỏi của bạn thành nhiều câu hỏi con
2. Tìm kiếm thông tin từ nhiều chiều trong biểu đồ mô phỏng
3. Tích hợp kết quả từ tìm kiếm ngữ nghĩa, phân tích thực thể, theo dõi chuỗi quan hệ
4. Trả về nội dung tìm kiếm toàn diện và sâu nhất

[Trường hợp sử dụng]
- Cần phân tích chuyên sâu một chủ đề
- Cần hiểu nhiều khía cạnh của sự kiện
- Cần thu thập tài liệu phong phú để hỗ trợ chương báo cáo

[Nội dung trả về]
- Văn bản gốc các sự kiện liên quan (có thể trích dẫn trực tiếp)
-insight cốt lõi về thực thể
- Phân tích chuỗi quan hệ"""

TOOL_DESC_PANORAMA_SEARCH = """\
[Tìm kiếm diện rộng - Thu thập toàn cảnh]
Công cụ này dùng để thu thập toàn cảnh đầy đủ của kết quả mô phỏng, đặc biệt phù hợp để hiểu quá trình biến đổi của sự kiện. Nó sẽ:
1. Thu thập tất cả các node và quan hệ liên quan
2. Phân biệt sự kiện hiệu lực hiện tại và sự kiện lịch sử/hết hiệu lực
3. Giúp bạn hiểu dư luận đã biến đổi như thế nào

[Trường hợp sử dụng]
- Cần hiểu toàn bộ quá trình phát triển của sự kiện
- Cần so sánh thay đổi dư luận ở các giai đoạn khác nhau
- Cần thu thập thông tin toàn diện về thực thể và quan hệ

[Nội dung trả về]
- Sự kiện hiệu lực hiện tại (kết quả mô phỏng mới nhất)
- Sự kiện lịch sử/hết hiệu lực (bản ghi biến đổi)
- Tất cả thực thể liên quan"""

TOOL_DESC_QUICK_SEARCH = """\
[Tìm kiếm nhanh - Tìm kiếm đơn giản]
Công cụ tìm kiếm nhẹ và nhanh, phù hợp cho truy vấn thông tin đơn giản, trực tiếp.

[Trường hợp sử dụng]
- Cần tìm nhanh một thông tin cụ thể
- Cần xác minh một sự kiện
- Tìm kiếm thông tin đơn giản

[Nội dung trả về]
- Danh sách các sự kiện liên quan nhất đến truy vấn"""

TOOL_DESC_INTERVIEW_AGENTS = """\
[Phỏng vấn chuyên sâu - Phỏng vấn Agent thật (hai nền tảng)]
Gọi API phỏng vấn của môi trường mô phỏng OASIS, thực hiện phỏng vấn thật các Agent đang chạy trong mô phỏng!
Đây không phải mô phỏng LLM, mà là gọi giao diện phỏng vấn thật để lấy câu trả lời gốc từ Agent mô phỏng.
Mặc định phỏng vấn đồng thời trên hai nền tảng Twitter và Reddit, thu thập quan điểm toàn diện hơn.

Quy trình hoạt động:
1. Tự động đọc file thiết lập nhân vật, hiểu tất cả Agent mô phỏng
2. Thông minh chọn Agent liên quan nhất đến chủ đề phỏng vấn (như học sinh, truyền thông, quan chức, v.v.)
3. Tự động sinh câu hỏi phỏng vấn
4. Gọi giao diện /api/simulation/interview/batch để phỏng vấn thật trên hai nền tảng
5. Tích hợp tất cả kết quả phỏng vấn, cung cấp phân tích đa góc nhìn

[Trường hợp sử dụng]
- Cần hiểu quan điểm sự kiện từ các vai trò khác nhau (học sinh nghĩ sao? truyền thông nghĩ sao? quan chức nói gì?)
- Cần thu thập ý kiến và lập trường từ nhiều phía
- Cần lấy câu trả lời thật từ Agent mô phỏng (từ môi trường mô phỏng OASIS)
- Muốn báo cáo sinh động hơn, bao gồm "ghi chép phỏng vấn"

[Nội dung trả về]
- Thông tin danh tính Agent được phỏng vấn
- Câu trả lời phỏng vấn của các Agent trên hai nền tảng Twitter và Reddit
- Trích dẫn quan trọng (có thể trích dẫn trực tiếp)
- Tóm tắt phỏng vấn và so sánh quan điểm

[Quan trọng] Cần môi trường mô phỏng OASIS đang chạy mới dùng được chức năng này!"""

# ── Prompt lên kế hoạch đề cương ──

PLAN_SYSTEM_PROMPT = """\
Bạn là chuyên gia viết "Báo cáo dự đoán tương lai", có "góc nhìn của Thượng Đế" về thế giới mô phỏng — bạn có thểinsight hành vi, lời nói và tương tác của mọi Agent trong mô phỏng.

[Triết lý cốt lõi]
Chúng tôi xây dựng một thế giới mô phỏng, và đưa vào đó "nhu cầu mô phỏng" cụ thể như biến số. Kết quả biến đổi của thế giới mô phỏng chính là dự đoán về những gì có thể xảy ra trong tương lai. Điều bạn đang quan sát không phải "dữ liệu thí nghiệm", mà là "buổi diễn tập tương lai".

[Nhiệm vụ của bạn]
Viết một "Báo cáo dự đoán tương lai", trả lời:
1. Trong điều kiện chúng tôi thiết lập, tương lai đã xảy ra điều gì?
2. Các loại Agent (nhóm người) đã phản ứng và hành động như thế nào?
3. Mô phỏng này tiết lộ những xu hướng và rủi ro tương lai đáng chú ý nào?

[Định vị báo cáo]
- ✅ Đây là báo cáo dự đoán tương lai dựa trên mô phỏng, tiết lộ "nếu thế này, tương lai sẽ ra sao"
- ✅ Tập trung vào kết quả dự đoán: diễn biến sự kiện, phản ứng nhóm, hiện tượng nổi lên, rủi ro tiềm ẩn
- ✅ Lời nói và hành vi của Agent trong thế giới mô phỏng chính là dự đoán hành vi nhóm người trong tương lai
- ❌ Không phải phân tích hiện trạng thế giới thực
- ❌ Không phải tổng quan dư luận chung chung

[Giới hạn số chương]
- Tối thiểu 2 chương, tối đa 5 chương
- Không cần chương con, mỗi chương viết nội dung hoàn chỉnh trực tiếp
- Nội dung phải cô đọng, tập trung vào phát hiện dự đoán cốt lõi
- Cấu trúc chương do bạn tự thiết kế dựa trên kết quả dự đoán

Vui lòng xuất dàn ý báo cáo định dạng JSON, như sau:
{
    "title": "Tiêu đề báo cáo",
    "summary": "Tóm tắt báo cáo (một câu khái quát phát hiện dự đoán cốt lõi)",
    "sections": [
        {
            "title": "Tiêu đề chương",
            "description": "Mô tả nội dung chương"
        }
    ]
}

Chú ý: Mảng sections tối thiểu 2, tối đa 5 phần tử!"""

PLAN_USER_PROMPT_TEMPLATE = """\
[Thiết lập tình huống dự đoán]
Biến số chúng tôi đưa vào thế giới mô phỏng (nhu cầu mô phỏng): {simulation_requirement}

[Quy mô thế giới mô phỏng]
- Số lượng thực thể tham gia mô phỏng: {total_nodes}
- Số lượng quan hệ giữa các thực thể: {total_edges}
- Phân bố loại thực thể: {entity_types}
- Số lượng Agent hoạt động: {total_entities}

[Mẫu một số sự kiện tương lai được mô phỏng dự đoán]
{related_facts_json}

Hãy xem xét buổi diễn tập tương lai này từ "góc nhìn của Thượng Đế":
1. Trong điều kiện chúng tôi thiết lập, tương lai thể hiện trạng thái như thế nào?
2. Các nhóm người (Agent) đã phản ứng và hành động ra sao?
3. Mô phỏng này tiết lộ những xu hướng tương lai đáng chú ý nào?

Dựa trên kết quả dự đoán, thiết kế cấu trúc chương báo cáo phù hợp nhất.

[Nhắc lại] Số chương báo cáo: tối thiểu 2, tối đa 5, nội dung phải cô đọng tập trung vào phát hiện dự đoán cốt lõi."""

# ── Prompt sinh chương ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
Bạn là chuyên gia viết "Báo cáo dự đoán tương lai", đang viết một chương của báo cáo.

Tiêu đề báo cáo: {report_title}
Tóm tắt báo cáo: {report_summary}
Tình huống dự đoán (nhu cầu mô phỏng): {simulation_requirement}

Chương hiện cần viết: {section_title}

═══════════════════════════════════════════════════════════════
[Triết lý cốt lõi]
═══════════════════════════════════════════════════════════════

Thế giới mô phỏng là buổi diễn tập tương lai. Chúng tôi đưa vào thế giới mô phỏng điều kiện cụ thể (nhu cầu mô phỏng),
hành vi và tương tác của Agent trong mô phỏng chính là dự đoán hành vi nhóm người trong tương lai.

Nhiệm vụ của bạn:
- Tiết lộ trong điều kiện thiết lập, tương lai đã xảy ra điều gì
- Dự đoán các nhóm người (Agent) đã phản ứng và hành động như thế nào
- Phát hiện xu hướng, rủi ro và cơ hội tương lai đáng chú ý

❌ Đừng viết thành phân tích hiện trạng thế giới thực
✅ Hãy tập trung vào "tương lai sẽ ra sao" — kết quả mô phỏng chính là tương lai được dự đoán

═══════════════════════════════════════════════════════════════
[Quy tắc quan trọng nhất - Bắt buộc tuân thủ]
═══════════════════════════════════════════════════════════════

1. [Bắt buộc gọi công cụ để quan sát thế giới mô phỏng]
   - Bạn đang dùng "góc nhìn của Thượng Đế" để quan sát buổi diễn tập tương lai
   - Mọi nội dung phải đến từ sự kiện xảy ra trong thế giới mô phỏng và lời nói/hành vi của Agent
   - Cấm sử dụng kiến thức của chính bạn để viết nội dung báo cáo
   - Mỗi chương ít nhất gọi 3 lần công cụ (tối đa 5 lần) để quan sát thế giới mô phỏng, nó đại diện cho tương lai

2. [Bắt buộc trích dẫn lời nói/hành vi gốc của Agent]
   - Lời nói và hành vi của Agent là dự đoán hành vi nhóm người trong tương lai
   - Trong báo cáo sử dụng định dạng trích dẫn để thể hiện các dự đoán này, ví dụ:
     > "Một nhóm người nào đó sẽ nói: nội dung gốc..."
   - Những trích dẫn này là bằng chứng cốt lõi của mô phỏng dự đoán

3. [Nhất quán ngôn ngữ - Nội dung trích dẫn phải dịch sang ngôn ngữ báo cáo]
   - Nội dung công cụ trả về có thể chứa diễn đạt khác với ngôn ngữ báo cáo
   - Báo cáo phải hoàn toàn sử dụng ngôn ngữ nhất quán với ngôn ngữ người dùng chỉ định
   - Khi bạn trích dẫn nội dung ngôn ngữ khác từ công cụ trả về, phải dịch sang ngôn ngữ báo cáo rồi mới viết vào
   - Khi dịch giữ nguyên ý gốc, đảm bảo diễn đạt tự nhiên trôi chảy
   - Quy tắc này áp dụng cho cả nội dung chính và khối trích dẫn (định dạng >)

4. [Trình bày trung thành kết quả dự đoán]
   - Nội dung báo cáo phải phản ánh kết quả mô phỏng đại diện cho tương lai trong thế giới mô phỏng
   - Đừng thêm thông tin không tồn tại trong mô phỏng
   - Nếu thông tin một khía cạnh nào đó không đủ, nói rõ sự thật

═══════════════════════════════════════════════════════════════
[⚠️ Quy cách định dạng - Cực kỳ quan trọng!]
═══════════════════════════════════════════════════════════════

[Một chương = Đơn vị nội dung nhỏ nhất]
- Mỗi chương là đơn vị phân khối nhỏ nhất của báo cáo
- ❌ Cấm sử dụng bất kỳ tiêu đề Markdown nào trong chương (#, ##, ###, ####, v.v.)
- ❌ Cấm thêm tiêu đề chính của chương ở đầu nội dung
- ✅ Tiêu đề chương do hệ thống tự động thêm, bạn chỉ cần viết nội dungnội dung chính thuần
- ✅ Sử dụng **in đậm**, phân cách đoạn, trích dẫn, danh sách để tổ chức nội dung, nhưng đừng dùng tiêu đề

[Ví dụ đúng]
```
Chương này phân tích tình hình lan truyền dư luận của sự kiện. Qua phân tích chuyên sâu dữ liệu mô phỏng, chúng tôi phát hiện...

**Giai đoạn bùng nổ ban đầu**

Weibo là hiện trường đầu tiên của dư luận, đảm nhiệm chức năng phát thông tin cốt lõi:

> "Weibo đóng góp 68% âm lượng phát đầu tiên..."

**Giai đoạn khuếch đại cảm xúc**

Nền tảng Douyin tiếp tục khuếch đại ảnh hưởng sự kiện:

- Tác động thị giác mạnh
- Độ cộng hưởng cảm xúc cao
```

[Ví dụ sai]
```
## Tóm tắt điều hành          ← Sai! Đừng thêm bất kỳ tiêu đề nào
### I. Giai đoạn ban đầu     ← Sai! Đừng dùng ### để phân tiểu mục
#### 1.1 Phân tích chi tiết ← Sai! Đừng dùng #### để phân nhỏ

Chương này phân tích...
```

═══════════════════════════════════════════════════════════════
[Công cụ tìm kiếm khả dụng] (mỗi chương gọi 3-5 lần)
═══════════════════════════════════════════════════════════════

{tools_description}

[Gợi ý sử dụng công cụ - Vui lòng kết hợp dùng nhiều công cụ khác nhau, đừng chỉ dùng một loại]
- insight_forge: Phân tíchinsight sâu, tự động chia nhỏ vấn đề và tìm kiếm đa chiều sự kiện và quan hệ
- panorama_search: Tìm kiếm toàn cảnh góc rộng, hiểu toàn bộ sự kiện, dòng thời gian và quá trình biến đổi
- quick_search: Xác minh nhanh một điểm thông tin cụ thể
- interview_agents: Phỏng vấn Agent mô phỏng, thu thập quan điểm góc nhìn thứ nhất và phản ứng thật từ các vai trò khác nhau

═══════════════════════════════════════════════════════════════
[Quy trình làm việc]
═══════════════════════════════════════════════════════════════

Mỗi lần trả lời bạn chỉ có thể làm một trong hai việc sau (không được đồng thời):

Tùy chọn A - Gọi công cụ:
Xuất ra suy nghĩ của bạn, rồi dùng định dạng sau để gọi một công cụ:
<tool_call>
{{"name": "Tên công cụ", "parameters": {{"Tên tham số": "Giá trị tham số"}}}}
</tool_call>
Hệ thống sẽ thực thi công cụ và trả kết quả về cho bạn. Bạn không cần và cũng không thể tự viết kết quả trả về của công cụ.

Tùy chọn B - Xuất nội dung cuối cùng:
Khi bạn đã qua công cụ thu thập đủ thông tin, bắt đầu bằng "Final Answer:" xuất nội dung chương.

⚠️ Cấm nghiêm ngặt:
- Cấm trong một lần trả lời đồng thời bao gồm gọi công cụ và Final Answer
- Cấm tự bịa kết quả trả về của công cụ (Observation), mọi kết quả công cụ do hệ thống tiêm vào
- Mỗi lần trả lời tối đa gọi một công cụ

═══════════════════════════════════════════════════════════════
[Yêu cầu nội dung chương]
═══════════════════════════════════════════════════════════════

1. Nội dung phải dựa trên dữ liệu mô phỏng tìm kiếm được từ công cụ
2. Trích dẫn nhiều văn bản gốc để thể hiện hiệu quả mô phỏng
3. Sử dụng định dạng Markdown (nhưng cấm dùng tiêu đề):
   - Sử dụng **chữ in đậm** đánh dấu trọng điểm (thay cho tiêu đề con)
   - Sử dụng danh sách (- hoặc 1.2.3.) tổ chức các điểm chính
   - Sử dụng dòng trống phân cách các đoạn khác nhau
   - ❌ Cấm sử dụng #, ##, ###, #### v.v. bất kỳ cú pháp tiêu đề nào
4. [Quy cách định dạng trích dẫn - Phải thành đoạn riêng]
   Trích dẫn phải độc lập thành đoạn, trước saucác có một dòng trống, không được trộn trong đoạn:

   ✅ Định dạng đúng:
   ```
   Phản hồi của nhà trường bị cho là thiếu nội dung thực chất.

   > "Mô hình ứng phó của nhà trường trong môi trường truyền thông xã hội biến đổi khôn lường tỏ ra cứng nhắc và chậm chạp."

   Đánh giá này phản ánh sự bất mãn phổ biến của công chúng.
   ```

   ❌ Định dạng sai:
   ```
   Phản hồi của nhà trường bị cho là thiếu nội dung thực chất. > "Mô hình ứng phó của nhà trường..." Đánh giá này phản ánh...
   ```
5. Giữ tính logic liên tục với các chương khác
6. [Tránh lặp lại] Đọc kỹ nội dung chương đã hoàn thành bên dưới, đừng mô tả lặp lại thông tin giống nhau
7. [Nhấn mạnh lại] Đừng thêm bất kỳ tiêu đề nào! Dùng **in đậm** thay cho tiêu đề tiểu mục"""

SECTION_USER_PROMPT_TEMPLATE = """\
Nội dung chương đã hoàn thành (vui lòng đọc kỹ, tránh lặp lại):
{previous_content}

═══════════════════════════════════════════════════════════════
[Nhiệm vụ hiện tại] Viết chương: {section_title}
═══════════════════════════════════════════════════════════════

[Nhắc nhở quan trọng]
1. Đọc kỹ chương đã hoàn thành ở trên, tránh lặp lại nội dung giống nhau!
2. Trước khi bắt đầu phải gọi công cụ để lấy dữ liệu mô phỏng
3. Vui lòng kết hợp dùng nhiều công cụ khác nhau, đừng chỉ dùng một loại
4. Nội dung báo cáo phải đến từ kết quả tìm kiếm, đừng sử dụng kiến thức của chính bạn

[⚠️ Cảnh báo định dạng - Phải tuân thủ]
- ❌ Đừng viết bất kỳ tiêu đề nào (#, ##, ###, #### đều không được)
- ❌ Đừng viết "{section_title}" làm phần mở đầu
- ✅ Tiêu đề chương do hệ thống tự động thêm
- ✅ Trực tiếp viếtnội dung chính, dùng **in đậm** thay cho tiêu đề tiểu mục

Hãy bắt đầu:
1. Đầu tiên suy nghĩ (Thought) chương này cần thông tin gì
2. Sau đó gọi công cụ (Action) để lấy dữ liệu mô phỏng
3. Sau khi thu thập đủ thông tin xuất Final Answer (nội dung chính thuần, không có bất kỳ tiêu đề nào)"""

# ── Mẫu tin nhắn trong vòng lặp ReACT ──

REACT_OBSERVATION_TEMPLATE = """\
Observation (Kết quả tìm kiếm):

═══ Công cụ {tool_name} trả về ═══
{result}

═══════════════════════════════════════════════════════════════
Đã gọi công cụ {tool_calls_count}/{max_tool_calls} lần (đã dùng: {used_tools_str}){unused_hint}
- Nếu thông tin đầy đủ: bắt đầu bằng "Final Answer:" xuất nội dung chương (phải trích dẫn văn bản gốc ở trên)
- Nếu cần thêm thông tin: gọi một công cụ để tiếp tục tìm kiếm
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "[Chú ý] Bạn chỉ gọi {tool_calls_count} lần công cụ, ít nhất cần {min_tool_calls} lần."
    "Vui lòng gọi thêm công cụ để lấy thêm dữ liệu mô phỏng, rồi xuất Final Answer.{unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "Hiện chỉ gọi {tool_calls_count} lần công cụ, ít nhất cần {min_tool_calls} lần."
    "Vui lòng gọi công cụ để lấy dữ liệu mô phỏng.{unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "Số lần gọi công cụ đã đạt giới hạn ({tool_calls_count}/{max_tool_calls}), không thể gọi thêm công cụ."
    'Vui lòng ngay lập tức dựa trên thông tin đã lấy, bắt đầu bằng "Final Answer:" xuất nội dung chương.'
)

REACT_UNUSED_TOOLS_HINT = "\n💡 Bạn chưa sử dụng: {unused_list}, gợi ý thử các công cụ khác nhau để lấy thông tin đa góc độ"

REACT_FORCE_FINAL_MSG = "Đã đạt giới hạn gọi công cụ, vui lòng trực tiếp xuất Final Answer: và tạo nội dung chương."

# ── Chat prompt ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
Bạn là trợ lý dự đoán mô phỏng đơn giản và hiệu quả.

[Bối cảnh]
Điều kiện dự đoán: {simulation_requirement}

[Báo cáo phân tích đã tạo]
{report_content}

[Quy tắc]
1. Ưu tiên dựa trên nội dung báo cáo ở trên để trả lời câu hỏi
2. Trực tiếp trả lời câu hỏi, tránh lập luận suy nghĩ dài dòng
3. Chỉ khi nội dung báo cáo không đủ để trả lời, mới gọi công cụ tìm kiếm thêm dữ liệu
4. Trả lời phải ngắn gọn, rõ ràng, có điều lý

[Công cụ khả dụng] (chỉ dùng khi cần, tối đa gọi 1-2 lần)
{tools_description}

[Định dạng gọi công cụ]
<tool_call>
{{"name": "Tên công cụ", "parameters": {{"Tên tham số": "Giá trị tham số"}}}}
</tool_call>

[Phong cách trả lời]
- Ngắn gọn trực tiếp, đừng dài dòng
- Sử dụng định dạng > để trích dẫn nội dung then chốt
- Ưu tiên đưa ra kết luận, rồi giải thích nguyên nhân"""

CHAT_OBSERVATION_SUFFIX = "\n\nVui lòng trả lời ngắn gọn câu hỏi."


# ═══════════════════════════════════════════════════════════════
# Lớp chính ReportAgent
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - Agent sinh báo cáo mô phỏng

    Sử dụng chế độ ReACT (Reasoning + Acting):
    1. Giai đoạn lập kế hoạch: Phân tích yêu cầu mô phỏng, lên kế hoạch cấu trúc thư mục báo cáo
    2. Giai đoạn sinh: Sinh nội dung từng chương, mỗi chương có thể gọi công cụ nhiều lần để lấy thông tin
    3. Giai đoạn phản ánh: Kiểm tra tính đầy đủ và chính xác của nội dung
    """
    
    # Số lần gọi công cụ tối đa (mỗi chương)
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # Số vòng phản ánh tối đa
    MAX_REFLECTION_ROUNDS = 3
    
    # Số lần gọi công cụ tối đa trong đối thoại
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        Khởi tạo Report Agent
        
        Args:
            graph_id: ID đồ thị
            simulation_id: ID mô phỏng
            simulation_requirement: Mô tả yêu cầu mô phỏng
            llm_client: Client LLM (tùy chọn)
            zep_tools: Dịch vụ công cụ Zep (tùy chọn)
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        
        # Định nghĩa công cụ
        self.tools = self._define_tools()
        
        # Bộ ghi nhật ký (khởi tạo trong generate_report)
        self.report_logger: Optional[ReportLogger] = None
        # Bộ ghi nhật ký console (khởi tạo trong generate_report)
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(t('report.agentInitDone', graphId=graph_id, simulationId=simulation_id))
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """Định nghĩa công cụ khả dụng"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "Vấn đề hoặc chủ đề bạn muốn phân tích sâu",
                    "report_context": "Ngữ cảnh chương báo cáo hiện tại (tùy chọn, giúp sinh sub-problem chính xác hơn)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "Truy vấn tìm kiếm, dùng cho sắp xếp tương quan",
                    "include_expired": "Có bao gồm nội dung hết hạn/lịch sử không (mặc định True)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "Chuỗi truy vấn tìm kiếm",
                    "limit": "Số lượng kết quả trả về (tùy chọn, mặc định 10)"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "Chủ đề phỏng vấn hoặc mô tả nhu cầu (vd: 'Tìm hiểu quan điểm của sinh viên về sự kiện formaldehyde ký túc xá')",
                    "max_agents": "Số Agent phỏng vấn tối đa (tùy chọn, mặc định 5, tối đa 10)"
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        Thực thi gọi công cụ
        
        Args:
            tool_name: Tên công cụ
            parameters: Tham số công cụ
            report_context: Ngữ cảnh báo cáo (dùng cho InsightForge)
            
        Returns:
            Kết quả thực thi công cụ (định dạng văn bản)
        """
        logger.info(t('report.executingTool', toolName=tool_name, params=parameters))
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # Tìm kiếm breadth - Lấy toàn cảnh
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # Tìm kiếm đơn giản - Tìm kiếm nhanh
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                # Phỏng vấn sâu - Gọi API phỏng vấn OASIS thật để lấy câu trả lời của Agent mô phỏng (hai nền tảng)
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()
            
            # ========== Công cụ cũ tương thích ngược (chuyển hướng nội bộ sang công cụ mới) ==========
            
            elif tool_name == "search_graph":
                # Chuyển hướng đến quick_search
                logger.info(t('report.redirectToQuickSearch'))
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # Chuyển hướng đến insight_forge, vì nó mạnh hơn
                logger.info(t('report.redirectToInsightForge'))
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"Công cụ không rõ: {tool_name}。Vui lòng sử dụng một trong các công cụ sau: insight_forge, panorama_search, quick_search"
                
        except Exception as e:
            logger.error(t('report.toolExecFailed', toolName=tool_name, error=str(e)))
            return f"Thực thi công cụ thất bại: {str(e)}"
    
    # Tập tên công cụ hợp lệ, dùng để kiểm tra khi phân tích JSON thô fallback
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Phân tích cú pháp gọi công cụ từ phản hồi LLM

        Định dạng hỗ trợ (theo độ ưu tiên):
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. JSON thô (toàn bộ phản hồi hoặc một dòng là JSON gọi công cụ)
        """
        tool_calls = []

        # Định dạng 1: Kiểu XML (định dạng chuẩn)
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Định dạng 2: Fallback - LLM xuất trực tiếp JSON thô (không bọc thẻ <tool_call>)
        # Chỉ thử khi định dạng 1 không khớp, tránh khớp nhầm JSON trong nội dung
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # Phản hồi có thể chứa văn bản suy nghĩ + JSON thô, thử trích xuất đối tượng JSON cuối cùng
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """Kiểm tra JSON phân tích có phải gọi công cụ hợp lệ không"""
        # Hỗ trợ hai loại key: {"name": ..., "parameters": ...} và {"tool": ..., "params": ...}
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # Thống nhất key thành name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """Sinh văn bản mô tả công cụ"""
        desc_parts = ["Công cụ khả dụng:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Tham số: {params_desc}")
        return "\n".join(desc_parts)
    
    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        Lên kế hoạch đề cương báo cáo
        
        Sử dụng LLM phân tích yêu cầu mô phỏng, lên kế hoạch cấu trúc thư mục báo cáo
        
        Args:
            progress_callback: Hàm callback tiến độ
            
        Returns:
            ReportOutline: Đề cương báo cáo
        """
        logger.info(t('report.startPlanningOutline'))
        
        if progress_callback:
            progress_callback("planning", 0, t('progress.analyzingRequirements'))
        
        # Đầu tiên lấy ngữ cảnh mô phỏng
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, t('progress.generatingOutline'))
        
        system_prompt = f"{PLAN_SYSTEM_PROMPT}\n\n{get_language_instruction()}"
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, t('progress.parsingOutline'))
            
            # Phân tích đề cương
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=response.get("title", "Báo cáo phân tích mô phỏng"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, t('progress.outlinePlanComplete'))
            
            logger.info(t('report.outlinePlanDone', count=len(sections)))
            return outline
            
        except Exception as e:
            logger.error(t('report.outlinePlanFailed', error=str(e)))
            # Trả về đề cương mặc định (3 chương, làm fallback)
            return ReportOutline(
                title="Báo cáo dự đoán tương lai",
                summary="Phân tích xu hướng tương lai và rủi ro dựa trên dự đoán mô phỏng",
                sections=[
                    ReportSection(title="Kịch bản dự đoán và phát hiện cốt lõi"),
                    ReportSection(title="Phân tích dự đoán hành vi nhóm người"),
                    ReportSection(title="Triển vọng xu hướng và cảnh báo rủi ro")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        Sử dụng chế độ ReACT để sinh nội dung một chương
        
        Vòng lặp ReACT:
        1. Thought (Suy nghĩ) - Phân tích cần thông tin gì
        2. Action (Hành động) - Gọi công cụ lấy thông tin
        3. Observation (Quan sát) - Phân tích kết quả công cụ trả về
        4. Lặp lại đến khi thông tin đủ hoặc đạt số lần tối đa
        5. Final Answer (Câu trả lời cuối) - Sinh nội dung chương
        
        Args:
            section: Chương cần sinh
            outline: Đề cương đầy đủ
            previous_sections: Nội dung các chương trước (dùng để giữ tính liên kết)
            progress_callback: callback tiến độ
            section_index: Chỉ mục chương (dùng để ghi nhật ký)
            
        Returns:
            Nội dung chương (định dạng Markdown)
        """
        logger.info(t('report.reactGenerateSection', title=section.title))
        
        # Ghi nhật ký bắt đầu chương
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # Xây dựng prompt người dùng - mỗi chương đã hoàn thành truyền tối đa 4000 ký tự
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # Mỗi chương tối đa 4000 ký tự
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(Đây là chương đầu tiên)"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Vòng lặp ReACT
        tool_calls_count = 0
        max_iterations = 5  # Số vòng lặp tối đa
        min_tool_calls = 3  # Số lần gọi công cụ tối thiểu
        conflict_retries = 0  # Số lần xung đột liên tiếp khi gọi công cụ và Final Answer xuất hiện cùng lúc
        used_tools = set()  # Ghi lại tên công cụ đã gọi
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Ngữ cảnh báo cáo, dùng để sinh sub-problem cho InsightForge
        report_context = f"Tiêu đề chương: {section.title}\nYêu cầu mô phỏng: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    t('progress.deepSearchAndWrite', current=tool_calls_count, max=self.MAX_TOOL_CALLS_PER_SECTION)
                )
            
            # Gọi LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=4096
            )

            # Kiểm tra LLM trả về có phải None không (API ngoại lệ hoặc nội dung rỗng)
            if response is None:
                logger.warning(t('report.sectionIterNone', title=section.title, iteration=iteration + 1))
                # Nếu còn số vòng lặp, thêm tin nhắn và thử lại
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(phản hồi rỗng)"})
                    messages.append({"role": "user", "content": "Vui lòng tiếp tục sinh nội dung."})
                    continue
                # Vòng lặp cuối cũng trả về None, thoát vòng lặp vào bắt buộc thu tail
                break

            logger.debug(f"Phản hồi LLM: {response[:200]}...")

            # Phân tích một lần, tái sử dụng kết quả
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── Xử lý xung đột: LLM đồng thời xuất gọi công cụ và Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    t('report.sectionConflict', title=section.title, iteration=iteration+1, conflictCount=conflict_retries)
                )

                if conflict_retries <= 2:
                    # Hai lần đầu: Vứt phản hồi này, yêu cầu LLM trả lời lại
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Lỗi định dạng] Bạn trong một lần trả lời đồng thời chứa gọi công cụ và Final Answer, điều này không được phép.\n"
                            "Mỗi lần trả lời chỉ được làm một trong hai việc sau:\n"
                            "- Gọi một công cụ (xuất một khối <tool_call>, không viết Final Answer)\n"
                            "- Xuất nội dung cuối (bắt đầu bằng 'Final Answer:', không chứa <tool_call>)\n"
                            "Vui lòng trả lời lại, chỉ làm một việc trong đó."
                        ),
                    })
                    continue
                else:
                    # Lần thứ ba: Xử lý giảm cấp, cắt đến gọi công cụ đầu tiên, bắt buộc thực thi
                    logger.warning(
                        t('report.sectionConflictDowngrade', title=section.title, conflictCount=conflict_retries)
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # Ghi nhật ký phản hồi LLM
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── Tình huống 1: LLM xuất Final Answer ──
            if has_final_answer:
                # Số lần gọi công cụ không đủ, từ chối và yêu cầu tiếp tục gọi công cụ
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"（Các công cụ này chưa được sử dụng, khuyến nghị dùng thử: {', '.join(unused_tools)}）" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # Kết thúc bình thường
                final_answer = response.split("Final Answer:")[-1].strip()
                logger.info(t('report.sectionGenDone', title=section.title, count=tool_calls_count))

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── Tình huống 2: LLM thử gọi công cụ ──
            if has_tool_calls:
                # Hạn mức công cụ đã hết → Thông báo rõ, yêu cầu xuất Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # Chỉ thực thi gọi công cụ đầu tiên
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(t('report.multiToolOnlyFirst', total=len(tool_calls), toolName=call['name']))

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # Xây dựng gợi ý công cụ chưa sử dụng
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list="、".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── Tình huống 3: Không có gọi công cụ, cũng không có Final Answer ──
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # Số lần gọi công cụ không đủ, gợi ý công cụ chưa dùng
                unused_tools = all_tools - used_tools
                unused_hint = f"（Các công cụ này chưa được sử dụng, khuyến nghị dùng thử: {', '.join(unused_tools)}）" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Gọi công cụ đã đủ, LLM xuất nội dung nhưng không có prefix "Final Answer:"
            # Trực tiếp lấy nội dung này làm câu trả lời cuối, không chạy không nữa
            logger.info(t('report.sectionNoPrefix', title=section.title, count=tool_calls_count))
            final_answer = response.strip()

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # Đạt số vòng lặp tối đa, bắt buộc sinh nội dung
        logger.warning(t('report.sectionMaxIter', title=section.title))
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            max_tokens=4096
        )

        # Kiểm tra khi bắt buộc thu tail LLM trả về có phải None không
        if response is None:
            logger.error(t('report.sectionForceFailed', title=section.title))
            final_answer = t('report.sectionGenFailedContent')
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response
        
        # Ghi nhật ký hoàn thành sinh nội dung chương
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        Sinh báo cáo đầy đủ (xuất realtime từng chương)
        
        Mỗi chương sinh xong lập tức lưu vào thư mục, không cần đợi cả báo cáo hoàn thành.
        Cấu trúc file:
        reports/{report_id}/
            meta.json       - Thông tin meta báo cáo
            outline.json    - Đề cương báo cáo
            progress.json   - Tiến độ sinh
            section_01.md   - Chương 1
            section_02.md   - Chương 2
            ...
            full_report.md  - Báo cáo đầy đủ
        
        Args:
            progress_callback: Hàm callback tiến độ (stage, progress, message)
            report_id: ID báo cáo (tùy chọn, nếu không truyền thì tự động sinh)
            
        Returns:
            Report: Báo cáo đầy đủ
        """
        import uuid
        
        # Nếu không truyền report_id, thì tự động sinh
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # Danh sách tiêu đề chương đã hoàn thành (dùng để theo dõi tiến độ)
        completed_section_titles = []
        
        try:
            # Khởi tạo: Tạo thư mục báo cáo và lưu trạng thái ban đầu
            ReportManager._ensure_report_folder(report_id)
            
            # Khởi tạo bộ ghi nhật ký（nhật ký có cấu trúc agent_log.jsonl）
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # Khởi tạo bộ ghi nhật ký console（console_log.txt）
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, t('progress.initReport'),
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # Giai đoạn 1: Lên kế hoạch đề cương
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, t('progress.startPlanningOutline'),
                completed_sections=[]
            )
            
            # Ghi nhật ký bắt đầu lên kế hoạch
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, t('progress.startPlanningOutline'))
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # Ghi nhật ký hoàn thành lên kế hoạch
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # Lưu đề cương vào file
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, t('progress.outlineDone', count=len(outline.sections)),
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(t('report.outlineSavedToFile', reportId=report_id))
            
            # Giai đoạn 2: Sinh từng chương (lưu từng chương)
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # Lưu nội dung dùng cho ngữ cảnh
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # Cập nhật tiến độ
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    t('progress.generatingSection', title=section.title, current=section_num, total=total_sections),
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )

                if progress_callback:
                    progress_callback(
                        "generating",
                        base_progress,
                        t('progress.generatingSection', title=section.title, current=section_num, total=total_sections)
                    )
                
                # Sinh nội dung chương chính
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # Lưu chương
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Ghi nhật ký hoàn thành chương
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(t('report.sectionSaved', reportId=report_id, sectionNum=f"{section_num:02d}"))
                
                # Cập nhật tiến độ
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    t('progress.sectionDone', title=section.title),
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # Giai đoạn 3: Lắp ráp báo cáo đầy đủ
            if progress_callback:
                progress_callback("generating", 95, t('progress.assemblingReport'))
            
            ReportManager.update_progress(
                report_id, "generating", 95, t('progress.assemblingReport'),
                completed_sections=completed_section_titles
            )
            
            # Sử dụng ReportManager lắp ráp báo cáo đầy đủ
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # Tính tổng thời gian
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # Ghi nhật ký hoàn thành báo cáo
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # Lưu báo cáo cuối cùng
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, t('progress.reportComplete'),
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, t('progress.reportComplete'))
            
            logger.info(t('report.reportGenDone', reportId=report_id))
            
            # Đóng bộ ghi nhật ký console
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(t('report.reportGenFailed', error=str(e)))
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # Ghi lại nhật ký lỗi
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # Lưu trạng thái thất bại
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, t('progress.reportFailed', error=str(e)),
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # Bỏ qua lỗi lưu thất bại
            
            # Đóng bộ ghi nhật ký console
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Đối thoại với Report Agent
        
        Trong đối thoại Agent có thể tự chủ gọi công cụ tìm kiếm để trả lời câu hỏi
        
        Args:
            message: Tin nhắn người dùng
            chat_history: Lịch sử đối thoại
            
        Returns:
            {
                "response": "Agent trả lời",
                "tool_calls": [Danh sách công cụ đã gọi],
                "sources": [Nguồn thông tin]
            }
        """
        logger.info(t('report.agentChat', message=message[:50]))
        
        chat_history = chat_history or []
        
        # Lấy nội dung báo cáo đã sinh
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # Giới hạn độ dài báo cáo, tránh ngữ cảnh quá dài
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [Nội dung báo cáo đã cắt ngắn] ..."
        except Exception as e:
            logger.warning(t('report.fetchReportFailed', error=e))
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "(Chưa có báo cáo)",
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        # Xây dựng tin nhắn
        messages = [{"role": "system", "content": system_prompt}]
        
        # Thêm lịch sử đối thoại
        for h in chat_history[-10:]:  # Giới hạn độ dài lịch sử
            messages.append(h)
        
        # Thêm tin nhắn người dùng
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # Vòng lặp ReACT（phiên bản đơn giản）
        tool_calls_made = []
        max_iterations = 2  # Giảm số vòng lặp
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # Phân tích cú pháp gọi công cụ
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # Không có gọi công cụ, trực tiếp trả về phản hồi
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # Thực thi gọi công cụ（Giới hạn số lượng）
            tool_results = []
            for call in tool_calls[:1]:  # Mỗi vòng tối đa thực thi 1 lần gọi công cụ
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # Giới hạn độ dài kết quả
                })
                tool_calls_made.append(call)
            
            # Thêm kết quả vào tin nhắn
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']}kết quả]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # Đạt tối đa vòng lặp, lấy phản hồi cuối cùng
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # Dọn dẹp phản hồi
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    Trình quản lý báo cáo
    
    Chịu trách nhiệm lưu trữ và truy xuất báo cáo
    
    Cấu trúc file (xuất từng chương):
    reports/
      {report_id}/
        meta.json          - Thông tin meta và trạng thái báo cáo
        outline.json       - Đề cương báo cáo
        progress.json      - Tiến độ sinh
        section_01.md      - Chương 1
        section_02.md      - Chương 2
        ...
        full_report.md     - Báo cáo đầy đủ
    """
    
    # Thư mục lưu trữ báo cáo
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """Đảm bảo thư mục gốc báo cáo tồn tại"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """Lấy đường dẫn thư mục báo cáo"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """Đảm bảo thư mục báo cáo tồn tại và trả về đường dẫn"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """Lấy đường dẫn file thông tin meta báo cáo"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """Lấy đường dẫn file Markdown báo cáo đầy đủ"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """Lấy đường dẫn file đề cương"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """Lấy đường dẫn file tiến độ"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """Lấy đường dẫn file Markdown chương"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Lấy đường dẫn file nhật ký Agent"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """Lấy đường dẫn file nhật ký console"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Lấy nội dung nhật ký console
        
        Đây là nhật ký xuất console trong quá trình sinh báo cáo (INFO, WARNING, v.v.),
        Khác với nhật ký có cấu trúc trong agent_log.jsonl.
        
        Args:
            report_id: ID báo cáo
            from_line: Bắt đầu đọc từ dòng thứ mấy (dùng cho lấy gia tăng, 0 nghĩa là từ đầu)
            
        Returns:
            {
                "logs": [Danh sách dòng nhật ký],
                "total_lines": Tổng số dòng,
                "from_line": Số dòng bắt đầu,
                "has_more": Có còn nhật ký nữa không
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # Giữ nguyên dòng nhật ký, bỏ ký tự xuống dòng cuối
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Đã đọc đến cuối
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        Lấy đầy đủ nhật ký console (lấy tất cả một lần)
        
        Args:
            report_id: ID báo cáo
            
        Returns:
            Danh sách dòng nhật ký
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Lấy nội dung nhật ký Agent
        
        Args:
            report_id: ID báo cáo
            from_line: Bắt đầu đọc từ dòng thứ mấy (dùng cho lấy gia tăng, 0 nghĩa là từ đầu)
            
        Returns:
            {
                "logs": [Danh sách mục nhật ký],
                "total_lines": Tổng số dòng,
                "from_line": Số dòng bắt đầu,
                "has_more": Có còn nhật ký nữa không
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # Bỏ qua dòng phân tích thất bại
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Đã đọc đến cuối
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Lấy đầy đủ nhật ký Agent (dùng cho lấy tất cả một lần)
        
        Args:
            report_id: ID báo cáo
            
        Returns:
            Danh sách mục nhật ký
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        Lưu đề cương báo cáo
        
        Gọi ngay sau khi hoàn thành giai đoạn lập kế hoạch
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(t('report.outlineSaved', reportId=report_id))
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        Lưu một chương

        Gọi ngay sau khi mỗi chương sinh xong, triển khai xuất từng chương

        Args:
            report_id: ID báo cáo
            section_index: Chỉ mục chương (bắt đầu từ 1)
            section: Đối tượng chương

        Returns:
            Đường dẫn file đã lưu
        """
        cls._ensure_report_folder(report_id)

        # Xây dựng nội dung Markdown chương - dọn dẹp các tiêu đề trùng có thể tồn tại
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # Lưu file
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(t('report.sectionFileSaved', reportId=report_id, fileSuffix=file_suffix))
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        Dọn dẹp nội dung chương
        
        1. Xóa các dòng tiêu đề Markdown trùng với tiêu đề chương ở đầu nội dung
        2. Chuyển tất cả tiêu đề cấp ### trở xuống thành văn bản in đậm
        
        Args:
            content: Nội dung gốc
            section_title: Tiêu đề chương
            
        Returns:
            Nội dung sau khi dọn dẹp
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Kiểm tra có phải dòng tiêu đề Markdown không
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # Kiểm tra xem có phải tiêu đề trùng với tiêu đề chương không (bỏ qua trùng trong 5 dòng đầu)
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # Chuyển tất cả tiêu đề các cấp (#, ##, ###, ####, v.v.) thành in đậm
                # Vì tiêu đề chương do hệ thống thêm, nội dung không nên có bất kỳ tiêu đề nào
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # Thêm dòng trống
                continue
            
            # Nếu dòng trước là tiêu đề bị bỏ qua, và dòng hiện tại rỗng, cũng bỏ qua
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # Xóa các dòng trống ở đầu
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # Xóa các đường phân cách ở đầu
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # Đồng thời xóa dòng trống sau đường phân cách
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        Cập nhật tiến độ sinh báo cáo
        
        Frontend có thể lấy tiến độ realtime bằng cách đọc progress.json
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """Lấy tiến độ sinh báo cáo"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Lấy danh sách chương đã sinh
        
        Trả về thông tin tất cả file chương đã lưu
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Phân tích chỉ mục chương từ tên file
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        Lắp ráp báo cáo đầy đủ
        
        Lắp ráp báo cáo đầy đủ từ các file chương đã lưu, và dọn dẹp tiêu đề
        """
        folder = cls._get_report_folder(report_id)
        
        # Xây dựng phần đầu báo cáo
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # Đọc tất cả file chương theo thứ tự
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # Hậu xử lý: Dọn dẹp vấn đề tiêu đề toàn bộ báo cáo
        md_content = cls._post_process_report(md_content, outline)
        
        # Lưu báo cáo đầy đủ
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(t('report.fullReportAssembled', reportId=report_id))
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        Hậu xử lý nội dung báo cáo
        
        1. Xóa tiêu đề trùng
        2. Giữ tiêu đề chính báo cáo (#) và tiêu đề chương (##), xóa các tiêu đề cấp khác (###, ####, v.v.)
        3. Dọn dẹp dòng trống và đường phân cách thừa
        
        Args:
            content: Nội dung báo cáo gốc
            outline: Đề cương báo cáo
            
        Returns:
            Nội dung sau khi xử lý
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # Thu thập tất cả tiêu đề chương từ đề cương
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Kiểm tra có phải dòng tiêu đề không
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Kiểm tra xem có phải tiêu đề trùng không (xuất hiện tiêu đề có nội dung giống nhau trong 5 dòng liên tiếp)
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # Bỏ qua tiêu đề trùng và dòng trống sau đó
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # Xử lý cấp tiêu đề:
                # - # (level=1) Chỉ giữ tiêu đề chính báo cáo
                # - ## (level=2) Giữ tiêu đề chương
                # - ### trở xuống (level>=3) Chuyển thành văn bản in đậm
                
                if level == 1:
                    if title == outline.title:
                        # Giữ tiêu đề chính báo cáo
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # Tiêu đề chương sai sử dụng #, sửa thành ##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # Các tiêu đề cấp một khác chuyển thành in đậm
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # Giữ tiêu đề chương
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # Tiêu đề cấp hai không phải chương chuyển thành in đậm
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # Tiêu đề cấp ### trở xuống chuyển thành văn bản in đậm
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # Bỏ qua đường phân cách ngay sau tiêu đề
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # Chỉ giữ một dòng trống sau tiêu đề
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # Dọn dẹp nhiều dòng trống liên tiếp (giữ tối đa 2 cái)
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """Lưu thông tin meta báo cáo và báo cáo đầy đủ"""
        cls._ensure_report_folder(report.report_id)
        
        # Lưu JSON thông tin meta
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Lưu đề cương
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # Lưu báo cáo Markdown đầy đủ
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(t('report.reportSaved', reportId=report.report_id))
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Lấy báo cáo"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # Tương thích định dạng cũ: Kiểm tra file lưu trực tiếp trong thư mục reports
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Xây dựng lại đối tượng Report
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # Nếu markdown_content rỗng, thử đọc từ full_report.md
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """Lấy báo cáo theo ID mô phỏng"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Định dạng mới: Thư mục
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # Tương thích định dạng cũ: File JSON
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """Liệt kê báo cáo"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Định dạng mới: Thư mục
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # Tương thích định dạng cũ: File JSON
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # Sắp xếp ngược theo thời gian tạo
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """Xóa báo cáo (toàn bộ thư mục)"""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # Định dạng mới: Xóa toàn bộ thư mục
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(t('report.reportFolderDeleted', reportId=report_id))
            return True
        
        # Tương thích định dạng cũ: Xóa file đơn lẻ
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
