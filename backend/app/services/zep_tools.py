"""
Dịch vụ công cụ tìm kiếm Zep
Đóng gói các công cụ tìm kiếm đồ thị, đọc node, truy vấn edge, v.v., dành cho Report Agent sử dụng

Công cụ tìm kiếm cốt lõi (sau tối ưu):
1. InsightForge (Tìm kiếm chuyên sâu) - Hỗn hợp tìm kiếm mạnh nhất, tự động sinh sub-problem và tìm kiếm đa chiều
2. PanoramaSearch (Tìm kiếm breadth) - Lấy toàn cảnh, bao gồm nội dung hết hạn
3. QuickSearch (Tìm kiếm đơn giản) - Tìm kiếm nhanh
"""

import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.locale import get_locale, t
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges

logger = get_logger('mirofish.zep_tools')


@dataclass
class SearchResult:
    """Kết quả tìm kiếm"""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }
    
    def to_text(self) -> str:
        """Chuyển sang định dạng văn bản, để LLM hiểu"""
        text_parts = [f"Truy vấn tìm kiếm: {self.query}", f"tìm thấy {self.total_count} thông tin liên quan"]
        
        if self.facts:
            text_parts.append("\n### Sự thực liên quan:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """Thông tin node"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }
    
    def to_text(self) -> str:
        """Chuyển sang định dạng văn bản"""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "loại không rõ")
        return f"entity: {self.name} (loại: {entity_type})\ntóm tắt: {self.summary}"


@dataclass
class EdgeInfo:
    """Thông tin edge"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # Thông tin thời gian
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }
    
    def to_text(self, include_temporal: bool = False) -> str:
        """Chuyển sang định dạng văn bản"""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"quan hệ: {source} --[{self.name}]--> {target}\nsự thực: {self.fact}"
        
        if include_temporal:
            valid_at = self.valid_at or "không rõ"
            invalid_at = self.invalid_at or "đến nay"
            base_text += f"\nhiệu lực: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (đã hết hạn: {self.expired_at})"
        
        return base_text
    
    @property
    def is_expired(self) -> bool:
        """Có đã hết hạn không"""
        return self.expired_at is not None
    
    @property
    def is_invalid(self) -> bool:
        """Có đã mất hiệu lực không"""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    Kết quả tìm kiếm chuyên sâu (InsightForge)
    Bao gồm kết quả tìm kiếm của nhiều sub-problem, và phân tích tổng hợp
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    
    # Kết quả tìm kiếm các chiều
    semantic_facts: List[str] = field(default_factory=list)  # Kết quả tìm kiếm ngữ nghĩa
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # Insight entity
    relationship_chains: List[str] = field(default_factory=list)  # Chuỗi quan hệ
    
    # Thông tin thống kê
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }
    
    def to_text(self) -> str:
        """Chuyển sang định dạng văn bản chi tiết, để LLM hiểu"""
        text_parts = [
            f"## Phân tích sâu dự đoán tương lai",
            f"Phân tích vấn đề: {self.query}",
            f"Kịch bản dự đoán: {self.simulation_requirement}",
            f"\n### Thống kê dữ liệu dự đoán",
            f"- Sự thực dự đoán liên quan: {self.total_facts} mục",
            f"- Entity liên quan: {self.total_entities} cái",
            f"- Chuỗi quan hệ: {self.total_relationships} mục"
        ]
        
        # sub-problem
        if self.sub_queries:
            text_parts.append(f"\n### Sub-problem đã phân tích")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")
        
        # Kết quả tìm kiếm ngữ nghĩa
        if self.semantic_facts:
            text_parts.append(f"\n### [Sự thực then chốt] (Vui lòng trích dẫn các văn bản gốc này trong báo cáo)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Insight entity
        if self.entity_insights:
            text_parts.append(f"\n### [Entity cốt lõi]")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', 'không rõ')}** ({entity.get('type', 'entity')})")
                if entity.get('summary'):
                    text_parts.append(f"  tóm tắt: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  Sự thực liên quan: {len(entity.get('related_facts', []))} mục")
        
        # Chuỗi quan hệ
        if self.relationship_chains:
            text_parts.append(f"\n### 【Chuỗi quan hệ】")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
        
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    Kết quả tìm kiếm breadth (Panorama)
    Bao gồm tất cả thông tin liên quan, bao gồm nội dung hết hạn
    """
    query: str
    
    # Tất cả node
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # Tất cả edge (bao gồm đã hết hạn)
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # Sự thực hiện có hiệu lực
    active_facts: List[str] = field(default_factory=list)
    # Sự thực đã hết hạn/mất hiệu lực (lịch sử ghi chép)
    historical_facts: List[str] = field(default_factory=list)
    
    # Thống kê
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }
    
    def to_text(self) -> str:
        """Chuyển sang định dạng văn bản（phiên bản đầy đủ, không cắt ngắn）"""
        text_parts = [
            f"## Kết quả tìm kiếm breadth（toàn cảnh tương lai）",
            f"Truy vấn: {self.query}",
            f"\n### Thông tin thống kê",
            f"- Tổng số node: {self.total_nodes}",
            f"- Tổng số edge: {self.total_edges}",
            f"- Sự thực hiện có hiệu lực: {self.active_count} mục",
            f"- Sự thực lịch sử/hết hạn: {self.historical_count} mục"
        ]
        
        # Sự thực hiện có hiệu lực（Xuất đầy đủ, không cắt ngắn）
        if self.active_facts:
            text_parts.append(f"\n### [Sự thực hiện có hiệu lực] (Văn bản gốc kết quả mô phỏng)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Sự thực lịch sử/hết hạn (xuất đầy đủ, không cắt ngắn)
        if self.historical_facts:
            text_parts.append(f"\n### [Sự thực lịch sử/hết hạn] (Ghi chép quá trình biến đổi)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Entity then chốt (xuất đầy đủ, không cắt ngắn)
        if self.all_nodes:
            text_parts.append(f"\n### [Entity liên quan]")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "entity")
                text_parts.append(f"- **{node.name}** ({entity_type})")
        
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """Kết quả phỏng vấn một Agent"""
    agent_name: str
    agent_role: str  # Loại vai trò (vd: sinh viên, giáo viên, truyền thông, v.v.)
    agent_bio: str  # Giới thiệu
    question: str  # Câu hỏi phỏng vấn
    response: str  # Câu trả lời phỏng vấn
    key_quotes: List[str] = field(default_factory=list)  # Trích dẫn then chốt
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }
    
    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        # Hiển thị đầy đủ agent_bio, không cắt ngắn
        text += f"_Giới thiệu: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**Trích dẫn then chốt:**\n"
            for quote in self.key_quotes:
                # Dọn dẹp các loại dấu ngoặc kép
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                # Bỏ dấu câu đầu
                while clean_quote and clean_quote[0] in '，,；;：:、。！？\n\r\t ':
                    clean_quote = clean_quote[1:]
                # Lọc nội dung rác chứa số câu hỏi (câu hỏi 1-9)
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # Cắt nội dung quá dài (cắt theo dấu câu, không cắt cứng)
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('\u3002', 80)
                    if dot_pos > 0:
                        clean_quote = clean_quote[:dot_pos + 1]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    Kết quả phỏng vấn (Interview)
    Bao gồm nhiều câu trả lời phỏng vấn từ các Agent mô phỏng
    """
    interview_topic: str  # Chủ đề phỏng vấn
    interview_questions: List[str]  # Danh sách câu hỏi phỏng vấn
    
    # Agent được chọn phỏng vấn
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # Câu trả lời phỏng vấn của các Agent
    interviews: List[AgentInterview] = field(default_factory=list)
    
    # Lý do chọn Agent
    selection_reasoning: str = ""
    # Tóm tắt phỏng vấn sau khi tổng hợp
    summary: str = ""
    
    # Thống kê
    total_agents: int = 0
    interviewed_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }
    
    def to_text(self) -> str:
        """Chuyển sang định dạng văn bản chi tiết, để LLM hiểuvà trích dẫn báo cáo"""
        text_parts = [
            "## Báo cáo phỏng vấn sâu",
            f"**Chủ đề phỏng vấn:** {self.interview_topic}",
            f"**số người phỏng vấn:** {self.interviewed_count} / {self.total_agents} Agent mô phỏng",
            "\n### Lý do chọn đối tượng phỏng vấn",
            self.selection_reasoning or "(Tự động chọn)",
            "\n---",
            "\n### Ghi chép phỏng vấn",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### phỏng vấn #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("(Không có ghi chép phỏng vấn)\n\n---")

        text_parts.append("\n### Tóm tắt phỏng vấn và quan điểm cốt lõi")
        text_parts.append(self.summary or "(Không có tóm tắt)")

        return "\n".join(text_parts)


class ZepToolsService:
    """
    Dịch vụ công cụ tìm kiếm Zep

    [Công cụ tìm kiếm cốt lõi - Sau tối ưu]
    1. insight_forge - Tìm kiếm chuyên sâu (mạnh nhất, tự động sinh sub-problem, tìm kiếm đa chiều)
    2. panorama_search - Tìm kiếm breadth (lấy toàn cảnh, bao gồm nội dung hết hạn)
    3. quick_search - Tìm kiếm đơn giản (tìm kiếm nhanh)
    4. interview_agents - Phỏng vấn sâu (phỏng vấn Agent mô phỏng, lấy quan điểm đa chiều)

    [Công cụ cơ bản]
    - search_graph - Tìm kiếm ngữ nghĩa đồ thị
    - get_all_nodes - Lấy tất cả node của đồ thị
    - get_all_edges - Lấy tất cả cạnh của đồ thị (bao gồm thông tin thời gian)
    - get_node_detail - Lấy thông tin chi tiết node
    - get_node_edges - Lấy edge liên quan node
    - get_entities_by_type - Lấy entity theo loại
    - get_entity_summary - Lấy tóm tắt quan hệ của entity
    """
    
    # Cấu hình retry
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY chưa được cấu hình")
        
        self.client = Zep(api_key=self.api_key)
        # Client LLM dùng cho InsightForge sinh sub-problem
        self._llm_client = llm_client
        logger.info(t("console.zepToolsInitialized"))
    
    @property
    def llm(self) -> LLMClient:
        """Khởi tạo trễ client LLM"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """Gọi API có cơ chế retry"""
        max_retries = max_retries or self.MAX_RETRIES
        last_exception = None
        delay = self.RETRY_DELAY
        
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        t("console.zepRetryAttempt", operation=operation_name, attempt=attempt + 1, error=str(e)[:100], delay=f"{delay:.1f}")
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(t("console.zepAllRetriesFailed", operation=operation_name, retries=max_retries, error=str(e)))
        
        raise last_exception
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Tìm kiếm ngữ nghĩa đồ thị
        
        Sử dụng tìm kiếm hỗn hợp (ngữ nghĩa+BM25) để tìm thông tin liên quan trong đồ thị.
        Nếu search API của Zep Cloud không khả dụng, thìgiảm cấp thành khớp từ khóa cục bộ.
        
        Args:
            graph_id: ID đồ thị (Standalone Graph)
            query: Truy vấn tìm kiếm
            limit: Số lượng kết quả trả về
            scope: Phạm vi tìm kiếm, "edges" hoặc "nodes"
            
        Returns:
            SearchResult: Kết quả tìm kiếm
        """
        logger.info(t("console.graphSearch", graphId=graph_id, query=query[:50]))
        
        # Thử sử dụng Zep Cloud Search API
        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope,
                    reranker="cross_encoder"
                ),
                operation_name=t("console.graphSearchOp", graphId=graph_id)
            )
            
            facts = []
            edges = []
            nodes = []
            
            # Phân tích kết quả tìm kiếm edge
            if hasattr(search_results, 'edges') and search_results.edges:
                for edge in search_results.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        facts.append(edge.fact)
                    edges.append({
                        "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                        "name": getattr(edge, 'name', ''),
                        "fact": getattr(edge, 'fact', ''),
                        "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                        "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    })
            
            # Phân tích kết quả tìm kiếm node
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # Tóm tắt node cũng tính là sự thực
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.searchComplete", count=len(facts)))
            
            return SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            logger.warning(t("console.zepSearchApiFallback", error=str(e)))
            # giảm cấp: Sử dụng tìm kiếm khớp từ khóa cục bộ
            return self._local_search(graph_id, query, limit, scope)
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Tìm kiếm khớp từ khóa cục bộ (làm phương ángiảm cấp cho Zep Search API)
        
        Lấy tất cả edge/node, sau đó khớp từ khóa cục bộ
        
        Args:
            graph_id: ID đồ thị
            query: Truy vấn tìm kiếm
            limit: Số lượng kết quả trả về
            scope: Phạm vi tìm kiếm
            
        Returns:
            SearchResult: Kết quả tìm kiếm
        """
        logger.info(t("console.usingLocalSearch", query=query[:30]))
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # Trích xuất từ khóa truy vấn (phân từ đơn giản)
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def match_score(text: str) -> int:
            """Tính điểm khớp giữa văn bản và truy vấn"""
            if not text:
                return 0
            text_lower = text.lower()
            # Khớp hoàn toàn truy vấn
            if query_lower in text_lower:
                return 100
            # Khớp từ khóa
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                # Lấy tất cả edge và khớp
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                # Sắp xếp theo điểm
                scored_edges.sort(key=lambda x: x[0], reverse=True)
                
                for score, edge in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                    })
            
            if scope in ["nodes", "both"]:
                # Lấy tất cả node và khớp
                all_nodes = self.get_all_nodes(graph_id)
                scored_nodes = []
                for node in all_nodes:
                    score = match_score(node.name) + match_score(node.summary)
                    if score > 0:
                        scored_nodes.append((score, node))
                
                scored_nodes.sort(key=lambda x: x[0], reverse=True)
                
                for score, node in scored_nodes[:limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.localSearchComplete", count=len(facts)))
            
        except Exception as e:
            logger.error(t("console.localSearchFailed", error=str(e)))
        
        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )
    
    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        Lấy tất cả node của đồ thị (lấy theo trang)

        Args:
            graph_id: ID đồ thị

        Returns:
            Danh sách node
        """
        logger.info(t("console.fetchingAllNodes", graphId=graph_id))

        nodes = fetch_all_nodes(self.client, graph_id)

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(t("console.fetchedNodes", count=len(result)))
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        Lấy tất cả cạnh của đồ thị (lấy theo trang, bao gồm thông tin thời gian)

        Args:
            graph_id: ID đồ thị
            include_temporal: Có bao gồm thông tin thời gian không (mặc định True)

        Returns:
            Danh sách edge (bao gồm created_at, valid_at, invalid_at, expired_at)
        """
        logger.info(t("console.fetchingAllEdges", graphId=graph_id))

        edges = fetch_all_edges(self.client, graph_id)

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            # Thêm thông tin thời gian
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(t("console.fetchedEdges", count=len(result)))
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        Lấy thông tin chi tiết của một node
        
        Args:
            node_uuid: UUID node
            
        Returns:
            Thông tin node hoặc None
        """
        logger.info(t("console.fetchingNodeDetail", uuid=node_uuid[:8]))
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=t("console.fetchNodeDetailOp", uuid=node_uuid[:8])
            )
            
            if not node:
                return None
            
            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except Exception as e:
            logger.error(t("console.fetchNodeDetailFailed", error=str(e)))
            return None
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        Lấy tất cả edge liên quan node
        
        Bằng cách lấy tất cả edge của đồ thị, sau đó lọc ra edge liên quan node chỉ định
        
        Args:
            graph_id: ID đồ thị
            node_uuid: UUID node
            
        Returns:
            Danh sách edge
        """
        logger.info(t("console.fetchingNodeEdges", uuid=node_uuid[:8]))
        
        try:
            # Lấy tất cả cạnh của đồ thị, sau đó lọc
            all_edges = self.get_all_edges(graph_id)
            
            result = []
            for edge in all_edges:
                # Kiểm tra edge có liên quan node chỉ định không (làm nguồn hoặc đích)
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(t("console.foundNodeEdges", count=len(result)))
            return result
            
        except Exception as e:
            logger.warning(t("console.fetchNodeEdgesFailed", error=str(e)))
            return []
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        Lấy entity theo loại
        
        Args:
            graph_id: ID đồ thị
            entity_type: Loại entity (vd Student, PublicFigure, v.v.)
            
        Returns:
            Danh sách entity phù hợp loại
        """
        logger.info(t("console.fetchingEntitiesByType", type=entity_type))
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # Kiểm tra labels có chứa loại chỉ định không
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(t("console.foundEntitiesByType", count=len(filtered), type=entity_type))
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        Lấy tóm tắt quan hệ của entity chỉ định
        
        Tìm kiếm tất cả thông tin liên quan entity đó, và sinh tóm tắt
        
        Args:
            graph_id: ID đồ thị
            entity_name: Tên entity
            
        Returns:
            Thông tin tóm tắt entity
        """
        logger.info(t("console.fetchingEntitySummary", name=entity_name))
        
        # Đầu tiên tìm kiếm thông tin liên quan entity đó
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # Thử tìm entity đó trong tất cả node
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # Truyền tham số graph_id
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)
        
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        Lấy thông tin thống kê của đồ thị

        Args:
            graph_id: ID đồ thị

        Returns:
            Thông tin thống kê
        """
        logger.info(t("console.fetchingGraphStats", graphId=graph_id))
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # Thống kê phân loại entity
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        # Thống kê phân loại quan hệ
        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }
    
    def get_simulation_context(
        self, 
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30
    ) -> Dict[str, Any]:
        """
        Lấy thông tin ngữ cảnh liên quan mô phỏng
        
        Tìm kiếm tổng hợp tất cả thông tin liên quan yêu cầu mô phỏng
        
        Args:
            graph_id: ID đồ thị
            simulation_requirement: Mô tả yêu cầu mô phỏng
            limit: Giới hạn số lượng mỗi loại thông tin
            
        Returns:
            Thông tin ngữ cảnh mô phỏng
        """
        logger.info(t("console.fetchingSimContext", requirement=simulation_requirement[:50]))
        
        # Tìm kiếm thông tin liên quan yêu cầu mô phỏng
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # Lấy thống kê đồ thị
        stats = self.get_graph_statistics(graph_id)
        
        # Lấy tất cả node entity
        all_nodes = self.get_all_nodes(graph_id)
        
        # Lọc entity có loại thực tế (không phải node Entity thuần)
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary
                })
        
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],  # Giới hạn số lượng
            "total_entities": len(entities)
        }
    
    # ========== Công cụ tìm kiếm cốt lõi (sau tối ưu) ==========
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """
        [InsightForge - Tìm kiếm chuyên sâu]

        Hàm tìm kiếm hỗn hợp mạnh nhất, tự động phân rã vấn đề và tìm kiếm đa chiều:
        1. Sử dụng LLM phân rã vấn đề thành nhiều sub-problem
        2. Tìm kiếm ngữ nghĩa cho mỗi sub-problem
        3. Trích xuất entity liên quan và lấy thông tin chi tiết
        4. Theo dõi chuỗi quan hệ
        5. Tổng hợp tất cả kết quả, sinh insight sâu

        Args:
            graph_id: ID đồ thị
            query: Vấn đề người dùng
            simulation_requirement: Mô tả yêu cầu mô phỏng
            report_context: Ngữ cảnh báo cáo (tùy chọn, dùng để sinh sub-problem chính xác hơn)
            max_sub_queries: Số sub-problem tối đa

        Returns:
            InsightForgeResult: Kết quả tìm kiếm chuyên sâu
        """
        logger.info(t("console.insightForgeStart", query=query[:50]))
        
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )
        
        # Step 1: Sử dụng LLM sinh sub-problem
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(t("console.generatedSubQueries", count=len(sub_queries)))
        
        # Step 2: Tìm kiếm ngữ nghĩa cho mỗi sub-problem
        all_facts = []
        all_edges = []
        seen_facts = set()
        
        for sub_query in sub_queries:
            search_result = self.search_graph(
                graph_id=graph_id,
                query=sub_query,
                limit=15,
                scope="edges"
            )
            
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            
            all_edges.extend(search_result.edges)
        
        # Tìm kiếm cả vấn đề gốc
        main_search = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=20,
            scope="edges"
        )
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)
        
        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)
        
        # Step 3: Trích xuất UUID entity liên quan từ cạnh, chỉ lấy thông tin các entity này (không lấy tất cả node)
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        # Lấy chi tiết tất cả entity liên quan (không giới hạn số lượng, xuất đầy đủ)
        entity_insights = []
        node_map = {}  # Dùng để xây dựng chuỗi quan hệ sau
        
        for uuid in list(entity_uuids):  # Xử lý tất cả entity, không cắt ngắn
            if not uuid:
                continue
            try:
                # Lấy riêng thông tin từng node liên quan
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "entity")
                    
                    # Lấy tất cả sự thực liên quan entity đó (không cắt ngắn)
                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts  # Xuất đầy đủ, không cắt ngắn
                    })
            except Exception as e:
                logger.debug(f"Lấy node {uuid} thất bại: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        # Step 4: Xây dựng tất cả chuỗi quan hệ (không giới hạn số lượng)
        relationship_chains = []
        for edge_data in all_edges:  # Xử lý tất cả edge, không cắt ngắn
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')
                
                source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or source_uuid[:8]
                target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or target_uuid[:8]
                
                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
        
        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)
        
        logger.info(t("console.insightForgeComplete", facts=result.total_facts, entities=result.total_entities, relationships=result.total_relationships))
        return result
    
    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """
        Sử dụng LLM sinh sub-problem
        
        Phân rã vấn đề phức tạp thành nhiều sub-problem có thể tìm kiếm độc lập
        """
        system_prompt = """Bạn là một chuyên gia phân tích câu hỏi chuyên nghiệp. Nhiệm vụ của bạn là chia nhỏ một câu hỏi phức tạp thành nhiều câu hỏi phụ có thể quan sát độc lập trong thế giới mô phỏng.

Yêu cầu:
1. Mỗi câu hỏi phụ phải đủ cụ thể để tìm thấy hành vi hoặc sự kiện liên quan của Agent trong thế giới mô phỏng
2. Các câu hỏi phụ nên bao phủ các khía cạnh khác nhau của câu hỏi gốc (như: ai, cái gì, tại sao, như thế nào, khi nào, ở đâu)
3. Các câu hỏi phụ phải liên quan đến kịch bản mô phỏng
4. Trả về định dạng JSON: {"sub_queries": ["Câu hỏi phụ 1", "Câu hỏi phụ 2", ...]}"""

        user_prompt = f"""Bối cảnh yêu cầu mô phỏng:
{simulation_requirement}

{f"Bối cảnh báo cáo: {report_context[:500]}" if report_context else ""}

Vui lòng chia câu hỏi sau thành {max_queries} câu hỏi phụ:
{query}

Trả về danh sách câu hỏi phụ dưới dạng JSON."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            # Đảm bảo là danh sách chuỗi
            return [str(sq) for sq in sub_queries[:max_queries]]
            
        except Exception as e:
            logger.warning(t("console.generateSubQueriesFailed", error=str(e)))
            # giảm cấp: Trả về biến thể dựa trên vấn đề gốc
            return [
                query,
                f"{query} người tham gia chính của",
                f"{query} nguyên nhân và ảnh hưởng của",
                f"{query} quá trình phát triển của"
            ][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """
        [PanoramaSearch - Tìm kiếm breadth]
        
        Lấy toàn cảnh, bao gồm tất cả nội dung liên quan và thông tin lịch sử/hết hạn:
        1. Lấy tất cả node liên quan
        2. Lấy tất cả edge (bao gồm đã hết hạn/mất hiệu lực)
        3. Phân loại và sắp xếp thông tin hiện có hiệu lực và lịch sử
        
        Công cụ này phù hợp cho các tình huống cần hiểu toàn cảnh sự kiện, theo dõi quá trình biến đổi.
        
        Args:
            graph_id: ID đồ thị
            query: Truy vấn tìm kiếm (dùng để sắp xếp theo độ liên quan)
            include_expired: Có bao gồm nội dung hết hạn không (mặc định True)
            limit: Số lượng kết quả trả về

        Returns:
            PanoramaResult: Kết quả tìm kiếm breadth
        """
        logger.info(t("console.panoramaSearchStart", query=query[:50]))
        
        result = PanoramaResult(query=query)
        
        # Lấy tất cả node
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # Lấy tất cả cạnh (bao gồm thông tin thời gian)
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        # Phân loại sự thực
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # Thêm tên entity cho sự thực
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # Kiểm tra có hết hạn/mất hiệu lực không
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                # Sự thực lịch sử/hết hạn, thêm marker thời gian
                valid_at = edge.valid_at or "không rõ"
                invalid_at = edge.invalid_at or edge.expired_at or "không rõ"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # Sự thực hiện có hiệu lực
                active_facts.append(edge.fact)

        # Sắp xếp theo độ liên quan dựa trên truy vấn
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # Sắp xếp và giới hạn số lượng
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(t("console.panoramaSearchComplete", active=result.active_count, historical=result.historical_count))
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        [QuickSearch - Tìm kiếm nhanh]

        Công cụ tìm kiếm nhanh, nhẹ:
        1. Gọi trực tiếp tìm kiếm ngữ nghĩa Zep
        2. Trả về kết quả liên quan nhất
        3. Phù hợp cho nhu cầu tìm kiếm đơn giản, trực tiếp

        Args:
            graph_id: ID đồ thị
            query: Truy vấn tìm kiếm
            limit: Số lượng kết quả trả về
            
        Returns:
            SearchResult: Kết quả tìm kiếm
        """
        logger.info(t("console.quickSearchStart", query=query[:50]))
        
        # Gọi trực tiếp phương thức search_graph hiện có
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        
        logger.info(t("console.quickSearchComplete", count=result.total_count))
        return result
    
    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None
    ) -> InterviewResult:
        """
        [InterviewAgents - Phỏng vấn sâu]

        Gọi API phỏng vấn OASIS thực tế, phỏng vấn các Agent đang chạy trong mô phỏng:
        1. Tự động đọc file nhân thiết, hiểu tất cả Agent mô phỏng
        2. Sử dụng LLM phân tích yêu cầu phỏng vấn, thông minh chọn Agent liên quan nhất
        3. Sử dụng LLM sinh câu hỏi phỏng vấn
        4. Gọi /api/simulation/interview/batch để phỏng vấn thực tế (đồng thời cả hai nền tảng)
        5. Tổng hợp tất cả kết quả phỏng vấn, sinh báo cáo phỏng vấn

        [Quan trọng] Chức năng này yêu cầu môi trường mô phỏng đang chạy (môi trường OASIS chưa đóng)

        [Tình huống sử dụng]
        - Cần hiểu quan điểm sự kiện từ góc độ các vai trò khác nhau
        - Cần thu thập ý kiến và quan điểm đa chiều
        - Cần lấy câu trả lời thực từ Agent mô phỏng (không phải LLM mô phỏng)

        Args:
            simulation_id: ID mô phỏng (dùng để định vị file nhân thiết và gọi API phỏng vấn)
            interview_requirement: Mô tả yêu cầu phỏng vấn (không cấu trúc, như "hiểu quan điểm học sinh về sự kiện")
            simulation_requirement: Bối cảnh yêu cầu mô phỏng (tùy chọn)
            max_agents: Số Agent phỏng vấn tối đa
            custom_questions: Câu hỏi phỏng vấn tùy chỉnh (tùy chọn, nếu không cung cấp sẽ tự động sinh)

        Returns:
            InterviewResult: Kết quả phỏng vấn
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(t("console.interviewAgentsStart", requirement=interview_requirement[:50]))
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Bước 1: Đọc file nhân thiết
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(t("console.profilesNotFound", simId=simulation_id))
            result.summary = "Không tìm thấy file nhân thiết Agent có thể phỏng vấn"
            return result
        
        result.total_agents = len(profiles)
        logger.info(t("console.loadedProfiles", count=len(profiles)))
        
        # Bước 2: Sử dụng LLM chọn Agent để phỏng vấn (trả về danh sách agent_id)
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(t("console.selectedAgentsForInterview", count=len(selected_agents), indices=selected_indices))
        
        # Bước 3: Sinh câu hỏi phỏng vấn (nếu không được cung cấp)
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(t("console.generatedInterviewQuestions", count=len(result.interview_questions)))
        
        # Gộp các câu hỏi thành một prompt phỏng vấn
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])

        # Thêm tiền tố tối ưu, ràng buộc định dạng trả lời của Agent
        INTERVIEW_PROMPT_PREFIX = (
            "Bạn đang tham gia một buổi phỏng vấn. Hãy kết hợp nhân thiết của bạn, tất cả ký ức và hành động quá khứ, "
            "trả lời trực tiếp các câu hỏi sau bằng văn bản thuần.\n"
            "Yêu cầu trả lời:\n"
            "1. Trực tiếp trả lời bằng ngôn ngữ tự nhiên, không gọi công cụ nào\n"
            "2. Không trả về định dạng JSON hoặc định dạng gọi công cụ\n"
            "3. Không sử dụng tiêu đề Markdown (như #, ##, ###)\n"
            "4. Trả lời lần lượt theo số câu hỏi, mỗi câu trả lời bắt đầu bằng「Câu hỏi X:」(X là số câu hỏi)\n"
            "5. Giữa các câu trả lời cách nhau bằng dòng trống\n"
            "6. Câu trả lời phải có nội dung thực chất, mỗi câu hỏi ít nhất 2-3 câu\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"
        
        # Bước 4: Gọi API phỏng vấn thực tế (không chỉ định platform, mặc định đồng thời cả hai nền tảng)
        try:
            # Xây dựng danh sách phỏng vấn hàng loạt (không chỉ định platform, phỏng vấn cả hai nền tảng)
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # Sử dụng prompt đã tối ưu
                    # Không chỉ định platform, API sẽ phỏng vấn cả hai nền tảng twitter và reddit
                })

            logger.info(t("console.callingBatchInterviewApi", count=len(interviews_request)))

            # Gọi phương thức phỏng vấn hàng loạt của SimulationRunner (không truyền platform, phỏng vấn cả hai nền tảng)
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # Không chỉ định platform, phỏng vấn cả hai nền tảng
                timeout=180.0   # Cần thời gian chờ lâu hơn cho cả hai nền tảng
            )

            logger.info(t("console.interviewApiReturned", count=api_result.get('interviews_count', 0), success=api_result.get('success')))

            # Kiểm tra API gọi có thành công không
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "lỗi không rõ")
                logger.warning(t("console.interviewApiReturnedFailure", error=error_msg))
                result.summary = f"Gọi API phỏng vấn thất bại: {error_msg}. Vui lòng kiểm tra trạng thái môi trường mô phỏng OASIS."
                return result

            # Bước 5: Phân tích kết quả trả về từ API, xây dựng đối tượng AgentInterview
            # Định dạng trả về chế độ hai nền tảng: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "không rõ")
                agent_bio = agent.get("bio", "")
                
                # Lấy kết quả phỏng vấn của Agent này trên cả hai nền tảng
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # Dọn dẹp JSON gọi công cụ có thể có
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # Luôn xuất marker hai nền tảng
                twitter_text = twitter_response if twitter_response else "（nền tảng này không nhận được phản hồi）"
                reddit_text = reddit_response if reddit_response else "（nền tảng này không nhận được phản hồi）"
                response_text = f"【Câu trả lời nền tảng Twitter】\n{twitter_text}\n\n【Câu trả lời nền tảng Reddit】\n{reddit_text}"

                # Trích dẫn then chốt (từ câu trả lời của cả hai nền tảng)
                import re
                combined_responses = f"{twitter_response} {reddit_response}"

                # Dọn dẹp văn bản phản hồi: loại bỏ marker, số, Markdown, v.v.
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'vấn đề\d+[：:]\s*', '', clean_text)
                clean_text = re.sub(r'【[^】]+】', '', clean_text)

                # Chiến lược 1 (chính): Trích xuất câu hoàn chỉnh có nội dung thực chất
                sentences = re.split(r'[。！？]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W，,；;：:、]+', s.strip())
                    and not s.strip().startswith(('{', 'vấn đề'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + "。" for s in meaningful[:3]]

                # Chiến lược 2 (bổ sung): Văn bản dài trong cặp dấu ngoặc kép「」đúng
                if not key_quotes:
                    paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[，,；;：:、]', q)][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],  # Mở rộng giới hạn độ dài bio
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # Môi trường mô phỏng chưa chạy
            logger.warning(t("console.interviewApiCallFailed", error=e))
            result.summary = f"Phỏng vấn thất bại: {str(e)}. Môi trường mô phỏng có thể đã đóng, vui lòng đảm bảo môi trường OASIS đang chạy."
            return result
        except Exception as e:
            logger.error(t("console.interviewApiCallException", error=e))
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"Quá trình phỏng vấn xảy ra lỗi: {str(e)}"
            return result

        # Bước 6: Sinh tóm tắt phỏng vấn
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        logger.info(t("console.interviewAgentsComplete", count=result.interviewed_count))
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """Dọn dẹp JSON gọi công cụ trong phản hồi của Agent, trích xuất nội dung thực tế"""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """Tải file nhân thiết Agent của mô phỏng"""
        import os
        import csv

        # Xây dựng đường dẫn file nhân thiết
        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # Ưu tiên thử đọc định dạng Reddit JSON
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(t("console.loadedRedditProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readRedditProfilesFailed", error=e))
        
        # Thử đọc định dạng Twitter CSV
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Chuyển đổi định dạng CSV sang định dạng thống nhất
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "không rõ"
                        })
                logger.info(t("console.loadedTwitterProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readTwitterProfilesFailed", error=e))
        
        return profiles
    
    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """
        Sử dụng LLM chọn Agent để phỏng vấn

        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: Danh sách thông tin đầy đủ của Agent được chọn
                - selected_indices: Danh sách chỉ số của Agent được chọn (dùng để gọi API)
                - reasoning: Lý do lựa chọn
        """

        # Xây dựng danh sách tóm tắt Agent
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "không rõ"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = """Bạn là một chuyên gia lập kế hoạch phỏng vấn chuyên nghiệp. Nhiệm vụ của bạn là chọn đối tượng phỏng vấn phù hợp nhất từ danh sách Agent mô phỏng dựa trên yêu cầu phỏng vấn.

Tiêu chí lựa chọn:
1. Danh tính/nghề nghiệp của Agent liên quan đến chủ đề phỏng vấn
2. Agent có thể giữ quan điểm độc đáo hoặc có giá trị
3. Lựa chọn đa dạng các góc nhìn (ví dụ: phe ủng hộ, phe phản đối, phe trung lập, chuyên gia, v.v.)
4. Ưu tiên chọn các vai trò liên quan trực tiếp đến sự kiện

Trả về định dạng JSON:
{
    "selected_indices": [danh sách chỉ số Agent được chọn],
    "reasoning": "Giải thích lý do lựa chọn"
}"""

        user_prompt = f"""Yêu cầu phỏng vấn:
{interview_requirement}

Bối cảnh mô phỏng:
{simulation_requirement if simulation_requirement else "Không có"}

Danh sách Agent có thể chọn (tổng cộng {len(agent_summaries)} cái):
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

Vui lòng chọn tối đa {max_agents} Agent phù hợp nhất để phỏng vấn và giải thích lý do lựa chọn."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "Tự động chọn dựa trên độ liên quan")

            # Lấy thông tin đầy đủ của Agent được chọn
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(t("console.llmSelectAgentFailed", error=e))
            # Giảm cấp: chọn N cái đầu tiên
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "Sử dụng chiến lược chọn mặc định"
    
    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """Sử dụng LLM sinh câu hỏi phỏng vấn"""
        
        agent_roles = [a.get("profession", "không rõ") for a in selected_agents]
        
        system_prompt = """Bạn là một nhà báo/phóng viên chuyên nghiệp. Dựa trên yêu cầu phỏng vấn, hãy tạo 3-5 câu hỏi phỏng vấn sâu.

Yêu cầu câu hỏi:
1. Câu hỏi mở, khuyến khích trả lời chi tiết
2. Các vai trò khác nhau có thể có câu trả lời khác nhau
3. Bao phủ nhiều khía cạnh như sự kiện, quan điểm, cảm xúc, v.v.
4. Ngôn ngữ tự nhiên, như một cuộc phỏng vấn thực tế
5. Mỗi câu hỏi giữ trong khoảng 50 từ trở lại, ngắn gọn rõ ràng
6. Hỏi trực tiếp, không bao gồm giải thích bối cảnh hoặc tiền tố

Trả về định dạng JSON: {"questions": ["Câu hỏi 1", "Câu hỏi 2", ...]}"""

        user_prompt = f"""Yêu cầu phỏng vấn: {interview_requirement}

Bối cảnh mô phỏng: {simulation_requirement if simulation_requirement else "Không có"}

Vai trò đối tượng phỏng vấn: {', '.join(agent_roles)}

Vui lòng tạo 3-5 câu hỏi phỏng vấn."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            return response.get("questions", [f"Về {interview_requirement}, bạn có quan điểm gì?"])

        except Exception as e:
            logger.warning(t("console.generateInterviewQuestionsFailed", error=e))
            return [
                f"Về {interview_requirement}, quan điểm của bạn là gì?",
                "Điều này ảnh hưởng thế nào đến bạn hoặc nhóm bạn đại diện?",
                "Bạn nghĩ nên giải quyết hoặc cải thiện những vấn đề này ra sao?"
            ]
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """Sinh tóm tắt phỏng vấn"""

        if not interviews:
            return "Chưa hoàn thành phỏng vấn nào"
        
        # Thu thập tất cả nội dung phỏng vấn
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f"【{interview.agent_name}（{interview.agent_role}）】\n{interview.response[:500]}")
        
        quote_instruction = "Sử dụng dấu ngoặc kép tiếng Việt「」khi trích dẫn lời người phỏng vấn" if get_locale() == 'zh' else 'Use quotation marks "" when quoting interviewees'
        system_prompt = f"""Bạn là một biên tập viên tin tức chuyên nghiệp. Vui lòng tạo bản tóm tắt phỏng vấn dựa trên câu trả lời của nhiều người phỏng vấn.

Yêu cầu tóm tắt:
1. Rút ra quan điểm chính của các bên
2. Chỉ ra sự đồng thuận và bất đồng trong quan điểm
3. Nổi bật những trích dẫn có giá trị
4. Khách quan trung lập, không thiên vị bất kỳ bên nào
5. Kiểm soát trong 1000 từ

Ràng buộc định dạng (phải tuân thủ):
- Sử dụng đoạn văn bản thuần, dùng dòng trống để phân cách các phần khác nhau
- Không sử dụng tiêu đề Markdown (như #, ##, ###)
- Không sử dụng đường phân cách (như ---, ***)
- {quote_instruction}
- Có thể sử dụng **in đậm** để đánh dấu từ khóa, nhưng không sử dụng cú pháp Markdown khác"""

        user_prompt = f"""Chủ đề phỏng vấn: {interview_requirement}

Nội dung phỏng vấn:
{"".join(interview_texts)}

Vui lòng tạo bản tóm tắt phỏng vấn."""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary
            
        except Exception as e:
            logger.warning(t("console.generateInterviewSummaryFailed", error=e))
            # Giảm cấp: ghép đơn giản
            return f"Đã phỏng vấn {len(interviews)} người, bao gồm: " + "、".join([i.agent_name for i in interviews])
