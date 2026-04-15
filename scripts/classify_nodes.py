#!/usr/bin/env python3
"""
Script để chạy lại node classification cho một project/graph cụ thể
Sử dụng khi simulation báo lỗi "Không tìm thấy thực thể nào phù hợp"
"""

import sys
import os

# Thêm backend vào path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.graph_builder import GraphBuilderService
from app.models.project import ProjectManager
from app.config import Config
from app.utils.locale import set_locale

def classify_nodes_for_project(project_id: str):
    """Chạy classification cho project"""
    set_locale('vi')

    print(f"=== Chạy classification cho project: {project_id} ===")

    # Lấy project info
    project = ProjectManager.get_project(project_id)
    if not project:
        print(f"Lỗi: Không tìm thấy project {project_id}")
        return False

    if not project.graph_id:
        print(f"Lỗi: Project không có graph_id")
        return False

    if not project.ontology:
        print(f"Lỗi: Project không có ontology")
        return False

    print(f"Graph ID: {project.graph_id}")
    print(f"Ontology có {len(project.ontology.get('entity_types', []))} entity types")

    # Tạo builder và chạy classification
    builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)

    def progress_callback(msg, ratio):
        print(f"  [{ratio*100:.0f}%] {msg}")

    print("\nBắt đầu classification...")
    classifications = builder._classify_nodes(
        project.graph_id,
        project.ontology,
        progress_callback=progress_callback
    )

    if classifications:
        print(f"\n✓ Classification hoàn tất: {len(classifications)} nodes được gán nhãn")

        # Verify: đọc lại project để kiểm tra
        project_updated = ProjectManager.get_project(project_id)
        if project_updated and project_updated.node_classifications:
            print(f"✓ Đã lưu classifications vào project")
            print(f"  Tổng số classifications: {len(project_updated.node_classifications)}")

            # Thống kê theo entity type
            type_counts = {}
            for entity_type in project_updated.node_classifications.values():
                type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
            print(f"  Phân bổ theo loại:")
            for etype, count in sorted(type_counts.items()):
                print(f"    {etype}: {count}")
        else:
            print(f"⚠ Không tìm thấy classifications trong project sau khi lưu")
            return False
    else:
        print(f"✗ Classification thất bại hoặc không có nodes nào được phân loại")
        return False

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python classify_nodes.py <project_id>")
        print("Ví dụ: python classify_nodes.py proj_a39214a21f50")
        sys.exit(1)

    project_id = sys.argv[1]
    success = classify_nodes_for_project(project_id)
    sys.exit(0 if success else 1)
