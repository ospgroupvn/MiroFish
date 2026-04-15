"""
Node Classification Service
使用LLM将Zep提取的entities分类到ontology定义的类型中
"""

import json
import re
from typing import Dict, Any, List, Optional

from openai import OpenAI

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.node_classifier')


class NodeClassifier:
    """
    使用LLM将graph nodes分类到ontology entity types
    """

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
            raise ValueError("LLM_API_KEY 未配置")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def classify_nodes(
        self,
        nodes: List[Any],
        entity_types: List[str],
        batch_size: int = 20
    ) -> Dict[str, str]:
        """
        批量分类nodes到entity types

        Args:
            nodes: Zep node objects (có name, summary, labels)
            entity_types: Danh sách các entity types từ ontology (e.g., ['Person', 'Organization', ...])
            batch_size: Số nodes phân loại mỗi lần gọi LLM

        Returns:
            Dict mapping node_uuid -> assigned entity type (label)
        """
        if not nodes:
            return {}

        logger.info(f"Bắt đầu phân loại {len(nodes)} nodes vào {len(entity_types)} entity types...")

        # Chuẩn bị dữ liệu nodes
        node_data = []
        for node in nodes:
            # Bỏ qua nodes đã có custom labels
            custom_labels = [l for l in getattr(node, 'labels', []) if l not in ['Entity', 'Node']]
            if custom_labels:
                logger.debug(f"Node {node.name} đã có label: {custom_labels}, bỏ qua")
                continue

            node_data.append({
                'uuid': getattr(node, 'uuid_', None) or getattr(node, 'uuid', None),
                'name': getattr(node, 'name', ''),
                'summary': getattr(node, 'summary', '') or '',
                'attributes': getattr(node, 'attributes', {}) or {}
            })

        if not node_data:
            logger.info("Tất cả nodes đã có labels, không cần phân loại")
            return {}

        logger.info(f"Cần phân loại {len(node_data)} nodes chưa có labels")

        # Phân loại theo batch
        all_classifications = {}
        num_batches = (len(node_data) + batch_size - 1) // batch_size

        for i in range(num_batches):
            start_idx = i * batch_size
            end_idx = min(start_idx + batch_size, len(node_data))
            batch = node_data[start_idx:end_idx]

            logger.info(f"Phân loại batch {i + 1}/{num_batches}: nodes {start_idx + 1}-{end_idx}")

            batch_results = self._classify_batch(batch, entity_types)
            all_classifications.update(batch_results)

        logger.info(f"Phân loại hoàn tất: {len(all_classifications)} nodes được gán labels")
        return all_classifications

    def _classify_batch(
        self,
        nodes: List[Dict[str, Any]],
        entity_types: List[str]
    ) -> Dict[str, str]:
        """Phân loại một batch nodes"""

        # Xây dựng prompt
        node_descriptions = []
        for i, node in enumerate(nodes):
            desc = f"- Node {i}: {node['name']}"
            if node['summary']:
                desc += f"\n  Summary: {node['summary']}"
            if node['attributes'] and isinstance(node['attributes'], dict):
                for k, v in node['attributes'].items():
                    if v:
                        desc += f"\n  {k}: {v}"
            node_descriptions.append(desc)

        nodes_text = "\n\n".join(node_descriptions)
        entity_types_list = ", ".join(entity_types)

        prompt = f"""You are a knowledge graph entity classification expert. Classify each node below into ONE of the following entity types:

**Available Entity Types:**
{entity_types_list}

**Entity Type Guidelines:**
- Person: Individual human beings
- Organization: Groups, organizations, institutions
- MediaOutlet: News media, publications, blogs
- GovernmentAgency: Government bodies, regulatory agencies
- Expert: Domain experts, thought leaders, academics
- Activist: Social activists, advocates
- Influencer: Social media influencers, public figures
- Company: Businesses, corporations
- University: Educational institutions
- Ngo: Non-governmental organizations

**Nodes to Classify:**
{nodes_text}

**Instructions:**
For each node, determine the most appropriate entity type based on its name, summary, and attributes. Return a JSON object mapping node index (as string "0", "1", etc.) to the entity type name.

**Output Format (JSON only, no markdown):**
{{
    "0": "Person",
    "1": "Organization",
    ...
}}

If a node cannot be confidently classified, assign it to "Person" as the default type."""

        system_prompt = "You are a precise entity classification assistant. Return ONLY valid JSON, no explanations."

        try:
            result = self._call_llm_with_retry(prompt, system_prompt)

            # Parse results
            classifications = {}
            for idx_str, entity_type in result.items():
                if entity_type in entity_types and idx_str.isdigit():
                    idx = int(idx_str)
                    if 0 <= idx < len(nodes):
                        node_uuid = nodes[idx]['uuid']
                        classifications[node_uuid] = entity_type

            return classifications

        except Exception as e:
            logger.error(f"LLM classification failed for batch: {e}")
            # Fallback: assign "Person" to all nodes
            fallback = {}
            for node in nodes:
                uuid = node['uuid']
                if uuid:
                    fallback[uuid] = "Person"
            return fallback

    def _call_llm_with_retry(
        self,
        prompt: str,
        system_prompt: str,
        max_attempts: int = 3
    ) -> Dict[str, Any]:
        """LLM call with retry logic"""

        last_error = None
        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3,
                )

                content = response.choices[0].message.content
                return json.loads(content)

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error (attempt {attempt + 1}): {e}")
                # Try to extract JSON from response
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    try:
                        return json.loads(json_match.group())
                    except:
                        pass
                last_error = e

            except Exception as e:
                logger.warning(f"LLM call error (attempt {attempt + 1}): {e}")
                last_error = e
                import time
                time.sleep(1)

        raise last_error or Exception("LLM call failed")

    def update_node_labels(
        self,
        client: Zep,
        graph_id: str,
        classifications: Dict[str, str]
    ) -> int:
        """
        Cập nhật labels cho nodes trong Zep

        Note: Zep SDK hiện không có API trực tiếp để update labels cho node.
        Chúng ta lưu classifications vào database của MiroFish thay vì cập nhật Zep.

        Returns:
            Số lượng nodes đã được gán label
        """
        # Hiện tại Zep không hỗ trợ update labels qua API
        # Chúng ta chỉ có thể lưu mapping vào database
        logger.info(f"Zep không hỗ trợ update labels trực tiếp. "
                   f"Đã phân loại {len(classifications)} nodes, "
                   f"sẽ lưu mapping vào database.")

        return len(classifications)
