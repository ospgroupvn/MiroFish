"""
Dịch vụ sinh ontology
Giao diện 1: Phân tích nội dung văn bản, sinh định nghĩa loại entity và quan hệ phù hợp cho mô phỏng xã hội
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.locale import get_language_instruction

logger = logging.getLogger(__name__)


def _to_pascal_case(name: str) -> str:
    """Chuyển đổi tên từ định dạng bất kỳ sang PascalCase (vd: 'works_for' -> 'WorksFor', 'person' -> 'Person')"""
    # Tách theo ký tự không phải chữ số/chữ cái
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # Tách tiếp theo ranh giới camelCase (vd: 'camelCase' -> ['camel', 'Case'])
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # Viết hoa chữ cái đầu mỗi từ, lọc chuỗi rỗng
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


# Prompt hệ thống cho việc sinh ontology
ONTOLOGY_SYSTEM_PROMPT = """Bạn là một chuyên gia thiết kế ontology cho knowledge graph. Nhiệm vụ của bạn is phân tích nội dung văn bản và yêu cầu mô phỏng đã cho, thiết kế các loại entity và loại quan hệ phù hợp cho **mô phỏng dư luận trên mạng xã hội**.

**Quan trọng: Bạn phải xuất dữ liệu ở định dạng JSON hợp lệ, không xuất bất kỳ nội dung nào khác.**

## Bối cảnh nhiệm vụ cốt lõi

Chúng ta đang xây dựng một **hệ thống mô phỏng dư luận trên mạng xã hội**. Trong hệ thống này:
- Mỗi entity đều là một "tài khoản" hoặc "chủ thể" có thể phát ngôn, tương tác, lan truyền thông tin trên mạng xã hội
- Các entity sẽ ảnh hưởng lẫn nhau, repost, bình luận, phản hồi
- Chúng ta cần mô phỏng phản ứng của các bên và đường lan truyền thông tin trong sự kiện dư luận

Do đó, **entity phải là các chủ thể có thật ngoài đời, có thể phát ngôn và tương tác trên MXH**:

**Có thể là**:
- Cá nhân cụ thể (người nổi tiếng, người trong cuộc, KOL, chuyên gia, người bình thường)
- Công ty, doanh nghiệp (bao gồm cả tài khoản chính thức)
- Tổ chức (trường đại học, hiệp hội, NGO, công đoàn, v.v.)
- Cơ quan chính phủ, cơ quan quản lý
- Tổ chức truyền thông (báo chí, đài truyền hình,truyền thông tự phát, website)
- Nền tảng mạng xã hộibản thân
- Đại diện nhóm cụ thể (như hội cựu sinh viên, fan club, nhóm bảo vệ quyền lợi, v.v.)

**Không thể là**:
- Khái niệm trừu tượng (như "dư luận", "cảm xúc", "xu hướng")
- Chủ đề/đề tài (như "chính trực học thuật", "cải cách giáo dục")
- Quan điểm/thái độ (như "phe ủng hộ", "phe phản đối")

## Định dạng xuất

Vui lòng xuất ở định dạng JSON, bao gồm cấu trúc sau:

```json
{
    "entity_types": [
        {
            "name": "Tên loại entity (tiếng Anh, PascalCase)",
            "description": "Mô tả ngắn (tiếng Anh, không quá 100 ký tự)",
            "attributes": [
                {
                    "name": "Tên thuộc tính (tiếng Anh, snake_case)",
                    "type": "text",
                    "description": "Mô tả thuộc tính"
                }
            ],
            "examples": ["Ví dụ entity 1", "Ví dụ entity 2"]
        }
    ],
    "edge_types": [
        {
            "name": "Tên loại quan hệ (tiếng Anh, UPPER_SNAKE_CASE)",
            "description": "Mô tả ngắn (tiếng Anh, không quá 100 ký tự)",
            "source_targets": [
                {"source": "Loại entity nguồn", "target": "Loại entity đích"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "Mô tả ngắn gọn về phân tích nội dung văn bản"
}
```

## Hướng dẫn thiết kế (cực kỳ quan trọng!)

### 1. Thiết kế loại entity - Phải tuân thủ nghiêm ngặt

**Yêu cầu số lượng: Phải đúng 10 loại entity**

**Yêu cầu cấu trúc phân tầng (phải bao gồm cả loại cụ thể và loại fallback)**:

10 loại entity của bạn phải bao gồm các tầng sau:

A. **Loại fallback (bắt buộc, đặt ở 2 vị trí cuối danh sách)**:
   - `Person`: Fallback cho bất kỳ cá nhân tự nhiên nào. Khi một người không thuộc loại người cụ thể nào khác, xếp vào loại này.
   - `Organization`: Fallback cho bất kỳ tổ chức nào. Khi một tổ chức không thuộc loại tổ chức cụ thể nào khác, xếp vào loại này.

B. **Loại cụ thể (8 loại, thiết kế theo nội dung văn bản)**:
   - Nhận diện các vai trò chính xuất hiện trong văn bản, thiết kế loại cụ thể hơn
   - Ví dụ: nếu văn bản liên quan sự kiện học thuật, có thể có `Student`, `Professor`, `University`
   - Ví dụ: nếu văn bản liên quan sự kiện kinh doanh, có thể có `Company`, `CEO`, `Employee`

**Tại sao cần loại fallback**:
- Văn bản sẽ xuất hiện nhiều loại người khác nhau, như "giáo viên tiểu học", "người qua đường", "một netizen nào đó"
- Nếu không có loại chuyên biệt phù hợp, họ nên được xếp vào `Person`
- Tương tự, tổ chức nhỏ, nhóm tạm thời, v.v. nên được xếp vào `Organization`

**Nguyên tắc thiết kế loại cụ thể**:
- Nhận diện các loại vai trò xuất hiện thường xuyên hoặc then chốt trong văn bản
- Mỗi loại cụ thể phải có ranh giới rõ ràng, tránh chồng chéo
- description phải nói rõ sự khác biệt giữa loại này và loại fallback

### 2. Thiết kế loại quan hệ

- Số lượng: 6-10
- Quan hệ nên phản ánh kết nối thực tế trong tương tác MXH
- Đảm bảo source_targets của quan hệ bao phủ các loại entity bạn đã định nghĩa

### 3. Thiết kế thuộc tính

- Mỗi loại entity 1-3 thuộc tính then chốt
- **Chú ý**: Tên thuộc tính không được dùng `name`, `uuid`, `group_id`, `created_at`, `summary` (đây là từ dành riêng của hệ thống)
- Khuyến nghị: `full_name`, `title`, `role`, `position`, `location`, `description`, v.v.

## Tham khảo loại entity

**Loại cá nhân (cụ thể)**:
- Student: Học sinh/Sinh viên
- Professor: Giáo sư/Học giả
- Journalist: Phóng viên
- Celebrity: Người nổi tiếng/Influencer
- Executive: Quản lý cấp cao
- Official: Quan chức chính phủ
- Lawyer: Luật sư
- Doctor: Bác sĩ

**Loại cá nhân (fallback)**:
- Person: Bất kỳ cá nhân tự nhiên nào (dùng khi không thuộc các loại cụ thể trên)

**Loại tổ chức (cụ thể)**:
- University: Trường đại học
- Company: Công ty doanh nghiệp
- GovernmentAgency: Cơ quan chính phủ
- MediaOutlet: Tổ chức truyền thông
- Hospital: Bệnh viện
- School: Trường phổ thông
- NGO: Tổ chức phi chính phủ

**Loại tổ chức (fallback)**:
- Organization: Bất kỳ tổ chức nào (dùng khi không thuộc các loại cụ thể trên)

## Tham khảo loại quan hệ

- WORKS_FOR: Làm việc tại
- STUDIES_AT: Học tại
- AFFILIATED_WITH: Thuộc về
- REPRESENTS: Đại diện
- REGULATES: Quản lý
- REPORTS_ON: Đưa tin về
- COMMENTS_ON: Bình luận về
- RESPONDS_TO: Phản hồi
- SUPPORTS: Ủng hộ
- OPPOSES: Phản đối
- COLLABORATES_WITH: Hợp tác
- COMPETES_WITH: Cạnh tranh
"""


class OntologyGenerator:
    """
    Bộ sinh ontology
    Phân tích nội dung văn bản, sinh định nghĩa loại entity và quan hệ
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sinh định nghĩa ontology

        Args:
            document_texts: Danh sách văn bản tài liệu
            simulation_requirement: Mô tả yêu cầu mô phỏng
            additional_context: Ngữ cảnh bổ sung

        Returns:
            Định nghĩa ontology (entity_types, edge_types, v.v.)
        """
        # Xây dựng thông điệp người dùng
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context
        )
        
        lang_instruction = get_language_instruction()
        system_prompt = f"{ONTOLOGY_SYSTEM_PROMPT}\n\n{lang_instruction}\nIMPORTANT: Entity type names MUST be in English PascalCase (e.g., 'PersonEntity', 'MediaOrganization'). Relationship type names MUST be in English UPPER_SNAKE_CASE (e.g., 'WORKS_FOR'). Attribute names MUST be in English snake_case. Only description fields and analysis_summary should use the specified language above."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # Gọi LLM
        try:
            result = self.llm_client.chat_json(
                messages=messages,
                temperature=0.3,
                max_tokens=4096
            )
            logger.info("LLM sinh ontology thành công")
        except Exception as e:
            logger.warning(f"LLM call thất bại: {str(e)}. Sử dụng fallback ontology generator...")
            result = self._generate_fallback_ontology(
                document_texts, simulation_requirement, additional_context
            )

        # Xác thực và xử lý hậu kỳ
        result = self._validate_and_process(result)

        return result
    
    # Độ dài tối đa của văn bản gửi cho LLM (50 nghìn ký tự)
    MAX_TEXT_LENGTH_FOR_LLM = 50000
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> str:
        """Xây dựng thông điệp người dùng"""
        
        # Gộp văn bản
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)
        
        # Nếu văn bản vượt quá 50 nghìn ký tự, cắt ngắn (chỉ ảnh hưởng đến nội dung gửi LLM, không ảnh hưởng đến xây dựng đồ thị)
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(Văn bản gốc có {original_length} ký tự, đã lấy {self.MAX_TEXT_LENGTH_FOR_LLM} ký tự đầu cho phân tích ontology)..."
        
        message = f"""## Yêu cầu mô phỏng

{simulation_requirement}

## Nội dung tài liệu

{combined_text}
"""
        
        if additional_context:
            message += f"""
## Ghi chú bổ sung

{additional_context}
"""
        
        message += """
Vui lòng dựa trên nội dung trên, thiết kế các loại entity và quan hệ phù hợp cho mô phỏng dư luận xã hội.

**Các quy tắc bắt buộc**：
1. Phải xuất chính xác 10 loại entity
2. 2 cái cuối phải là loại fallback: Person (fallback cá nhân) và Organization (fallback tổ chức)
3. 8 cái đầu là loại cụ thể thiết kế theo nội dung văn bản
4. Tất cả loại entity phải là chủ thể có thể phát ngôn trong thực tế, không được là khái niệm trừu tượng
5. Tên thuộc tính không được dùng từ dành riêng như name, uuid, group_id, hãy dùng full_name, org_name, v.v.
"""
        
        return message
    
    def _validate_and_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Xác thực và xử lý hậu kỳ kết quả"""
        
        # Đảm bảo các trường cần thiết tồn tại
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # Xác thực loại entity
        # Ghi lại ánh xạ tên gốc sang PascalCase, dùng để sửa tham chiếu source_targets của edge
        entity_name_map = {}
        for entity in result["entity_types"]:
            # Bắt buộc chuyển tên entity sang PascalCase (yêu cầu Zep API)
            if "name" in entity:
                original_name = entity["name"]
                entity["name"] = _to_pascal_case(original_name)
                if entity["name"] != original_name:
                    logger.warning(f"Entity type name '{original_name}' auto-converted to '{entity['name']}'")
                entity_name_map[original_name] = entity["name"]
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # Đảm bảo description không vượt quá 100 ký tự
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # Xác thực loại quan hệ
        for edge in result["edge_types"]:
            # Bắt buộc chuyển tên edge sang SCREAMING_SNAKE_CASE (yêu cầu Zep API)
            if "name" in edge:
                original_name = edge["name"]
                edge["name"] = original_name.upper()
                if edge["name"] != original_name:
                    logger.warning(f"Edge type name '{original_name}' auto-converted to '{edge['name']}'")
            # Sửa tham chiếu tên entity trong source_targets, đồng bộ với PascalCase đã chuyển
            for st in edge.get("source_targets", []):
                if st.get("source") in entity_name_map:
                    st["source"] = entity_name_map[st["source"]]
                if st.get("target") in entity_name_map:
                    st["target"] = entity_name_map[st["target"]]
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # Giới hạn Zep API: tối đa 10 loại entity tùy chỉnh, tối đa 10 loại edge tùy chỉnh
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        # Loại bỏ trùng: theo name, giữ lại cái xuất hiện đầu
        seen_names = set()
        deduped = []
        for entity in result["entity_types"]:
            name = entity.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(entity)
            elif name in seen_names:
                logger.warning(f"Duplicate entity type '{name}' removed during validation")
        result["entity_types"] = deduped

        # Định nghĩa loại fallback
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # Kiểm tra xem đã có loại fallback chưa
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # Loại fallback cần thêm
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # Nếu thêm vào vượt quá 10 cái, cần xóa bớt một số loại hiện có
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # Tính số lượng cần xóa
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # Xóa từ cuối (giữ lại loại cụ thể quan trọng hơn ở phía trước)
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # Thêm loại fallback
            result["entity_types"].extend(fallbacks_to_add)
        
        # Cuối cùng đảm bảo không vượt giới hạn (lập trình phòng vệ)
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
        
        return result

    def _generate_fallback_ontology(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str]
    ) -> Dict[str, Any]:
        """

Cung cấp các entity và relation cơ bản cho mô phỏng mạng xã hội
        """
        combined_text = "\n\n".join(document_texts)
        # Tạo tóm tắt đơn giản từ văn bản
        summary = f"Ontology generated from {len(combined_text)} characters of content. Simulation requirement: {simulation_requirement[:200]}"

        return {
            "entity_types": [
                {
                    "name": "Person",
                    "description": "Any individual person participating in social media",
                    "attributes": [
                        {"name": "full_name", "type": "text", "description": "Full name"},
                        {"name": "role", "type": "text", "description": "Role or occupation"}
                    ],
                    "examples": ["user", "individual"]
                },
                {
                    "name": "Organization",
                    "description": "Any organization or group entity",
                    "attributes": [
                        {"name": "org_name", "type": "text", "description": "Organization name"},
                        {"name": "org_type", "type": "text", "description": "Type of organization"}
                    ],
                    "examples": ["company", "institution"]
                },
                {
                    "name": "MediaOutlet",
                    "description": "Media organization or news outlet",
                    "attributes": [
                        {"name": "outlet_name", "type": "text", "description": "Name of the media outlet"},
                        {"name": "media_type", "type": "text", "description": "Type of media (news, blog, etc.)"}
                    ],
                    "examples": ["news agency", "online publication"]
                },
                {
                    "name": "GovernmentAgency",
                    "description": "Government or regulatory body",
                    "attributes": [
                        {"name": "agency_name", "type": "text", "description": "Name of the agency"},
                        {"name": "jurisdiction", "type": "text", "description": "Area of jurisdiction"}
                    ],
                    "examples": ["regulatory body", "government department"]
                },
                {
                    "name": "Expert",
                    "description": "Domain expert or thought leader",
                    "attributes": [
                        {"name": "expert_name", "type": "text", "description": "Name of the expert"},
                        {"name": "field", "type": "text", "description": "Area of expertise"}
                    ],
                    "examples": ["analyst", "researcher"]
                },
                {
                    "name": "Activist",
                    "description": "Social activist or advocate",
                    "attributes": [
                        {"name": "activist_name", "type": "text", "description": "Name of the activist"},
                        {"name": "cause", "type": "text", "description": "Cause they advocate for"}
                    ],
                    "examples": ["campaigner", "advocate"]
                },
                {
                    "name": "Influencer",
                    "description": "Social media influencer with significant following",
                    "attributes": [
                        {"name": "influencer_name", "type": "text", "description": "Name of the influencer"},
                        {"name": "platform", "type": "text", "description": "Primary social media platform"}
                    ],
                    "examples": ["content creator", "key opinion leader"]
                },
                {
                    "name": "Company",
                    "description": "Business or corporate entity",
                    "attributes": [
                        {"name": "company_name", "type": "text", "description": "Name of the company"},
                        {"name": "industry", "type": "text", "description": "Industry sector"}
                    ],
                    "examples": ["corporation", "startup"]
                },
                {
                    "name": "University",
                    "description": "Educational or research institution",
                    "attributes": [
                        {"name": "uni_name", "type": "text", "description": "Name of the institution"},
                        {"name": "focus_area", "type": "text", "description": "Primary academic focus"}
                    ],
                    "examples": ["research university", "college"]
                },
                {
                    "name": "NGO",
                    "description": "Non-governmental organization",
                    "attributes": [
                        {"name": "ngo_name", "type": "text", "description": "Name of the NGO"},
                        {"name": "mission", "type": "text", "description": "Primary mission or focus"}
                    ],
                    "examples": ["non-profit", "charity"]
                }
            ],
            "edge_types": [
                {
                    "name": "WORKS_FOR",
                    "description": "Employment or affiliation relationship",
                    "source_targets": [
                        {"source": "Person", "target": "Organization"},
                        {"source": "Person", "target": "Company"},
                        {"source": "Person", "target": "University"}
                    ],
                    "attributes": []
                },
                {
                    "name": "AFFILIATED_WITH",
                    "description": "General affiliation or association",
                    "source_targets": [
                        {"source": "Person", "target": "Organization"},
                        {"source": "Organization", "target": "Organization"}
                    ],
                    "attributes": []
                },
                {
                    "name": "RESPONDS_TO",
                    "description": "One entity responds to another",
                    "source_targets": [
                        {"source": "Person", "target": "Person"},
                        {"source": "Organization", "target": "Person"},
                        {"source": "Organization", "target": "Organization"}
                    ],
                    "attributes": []
                },
                {
                    "name": "SUPPORTS",
                    "description": "One entity supports another",
                    "source_targets": [
                        {"source": "Person", "target": "Person"},
                        {"source": "Organization", "target": "Person"},
                        {"source": "Organization", "target": "Organization"}
                    ],
                    "attributes": []
                },
                {
                    "name": "OPPOSES",
                    "description": "One entity opposes another",
                    "source_targets": [
                        {"source": "Person", "target": "Person"},
                        {"source": "Organization", "target": "Person"},
                        {"source": "Organization", "target": "Organization"}
                    ],
                    "attributes": []
                },
                {
                    "name": "REPORTS_ON",
                    "description": "Media reports on an entity or event",
                    "source_targets": [
                        {"source": "MediaOutlet", "target": "Person"},
                        {"source": "MediaOutlet", "target": "Organization"},
                        {"source": "MediaOutlet", "target": "Company"}
                    ],
                    "attributes": []
                },
                {
                    "name": "REGULATES",
                    "description": "Government agency regulates an entity",
                    "source_targets": [
                        {"source": "GovernmentAgency", "target": "Company"},
                        {"source": "GovernmentAgency", "target": "Organization"}
                    ],
                    "attributes": []
                },
                {
                    "name": "COLLABORATES_WITH",
                    "description": "Two entities collaborate",
                    "source_targets": [
                        {"source": "Person", "target": "Person"},
                        {"source": "Organization", "target": "Organization"},
                        {"source": "Person", "target": "Organization"}
                    ],
                    "attributes": []
                },
                {
                    "name": "INFLUENCES",
                    "description": "One entity influences another",
                    "source_targets": [
                        {"source": "Influencer", "target": "Person"},
                        {"source": "Expert", "target": "Person"},
                        {"source": "MediaOutlet", "target": "Person"}
                    ],
                    "attributes": []
                },
                {
                    "name": "ADVOCATES_FOR",
                    "description": "One entity advocates for a cause or group",
                    "source_targets": [
                        {"source": "Activist", "target": "Person"},
                        {"source": "NGO", "target": "Person"},
                        {"source": "Activist", "target": "Organization"}
                    ],
                    "attributes": []
                }
            ],
            "analysis_summary": summary
        }

    def generate_python_code(self, ontology: Dict[str, Any]) -> str:
        """
        Chuyển định nghĩa ontology sang mã Python (tương tự ontology.py)

        Args:
            ontology: Định nghĩa ontology

        Returns:
            Chuỗi mã Python
        """
        code_lines = [
            '"""',
            'Định nghĩa loại entity tùy chỉnh',
            'Được MiroFish sinh tự động, dùng cho mô phỏng dư luận xã hội',
            '"""',
            '',
            'from pydantic import Field',
            'from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel',
            '',
            '',
            '# ============== Định nghĩa loại entity ==============',
            '',
        ]

        # Sinh loại entity
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            desc = entity.get("description", f"A {name} entity.")
            
            code_lines.append(f'class {name}(EntityModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = entity.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        code_lines.append('# ============== Định nghĩa loại quan hệ ==============')
        code_lines.append('')
        
        # Sinh loại quan hệ
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            # Chuyển sang tên class PascalCase
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            desc = edge.get("description", f"A {name} relationship.")
            
            code_lines.append(f'class {class_name}(EdgeModel):')
            code_lines.append(f'    """{desc}"""')
            
            attrs = edge.get("attributes", [])
            if attrs:
                for attr in attrs:
                    attr_name = attr["name"]
                    attr_desc = attr.get("description", attr_name)
                    code_lines.append(f'    {attr_name}: EntityText = Field(')
                    code_lines.append(f'        description="{attr_desc}",')
                    code_lines.append(f'        default=None')
                    code_lines.append(f'    )')
            else:
                code_lines.append('    pass')
            
            code_lines.append('')
            code_lines.append('')
        
        # Sinh từ điển loại
        code_lines.append('# ============== Cấu hình loại ==============')
        code_lines.append('')
        code_lines.append('ENTITY_TYPES = {')
        for entity in ontology.get("entity_types", []):
            name = entity["name"]
            code_lines.append(f'    "{name}": {name},')
        code_lines.append('}')
        code_lines.append('')
        code_lines.append('EDGE_TYPES = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            code_lines.append(f'    "{name}": {class_name},')
        code_lines.append('}')
        code_lines.append('')
        
        # Sinh ánh xạ source_targets của edge
        code_lines.append('EDGE_SOURCE_TARGETS = {')
        for edge in ontology.get("edge_types", []):
            name = edge["name"]
            source_targets = edge.get("source_targets", [])
            if source_targets:
                st_list = ', '.join([
                    f'{{"source": "{st.get("source", "Entity")}", "target": "{st.get("target", "Entity")}"}}'
                    for st in source_targets
                ])
                code_lines.append(f'    "{name}": [{st_list}],')
        code_lines.append('}')
        
        return '\n'.join(code_lines)

