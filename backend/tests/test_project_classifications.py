"""
Tests for Project model node_classifications field
"""

import json
import os
import tempfile
import shutil
from datetime import datetime

import pytest

from app.models.project import Project, ProjectStatus, ProjectManager


@pytest.fixture
def temp_projects_dir():
    """Tạo thư mục tạm cho projects"""
    temp_dir = tempfile.mkdtemp()
    original_dir = ProjectManager.PROJECTS_DIR
    ProjectManager.PROJECTS_DIR = temp_dir
    yield temp_dir
    ProjectManager.PROJECTS_DIR = original_dir
    shutil.rmtree(temp_dir)


def test_project_has_node_classifications_field():
    """Test rằng Project dataclass có trường node_classifications"""
    project = Project(
        project_id="proj_test",
        name="Test Project",
        status=ProjectStatus.CREATED,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    assert hasattr(project, 'node_classifications')
    assert project.node_classifications is None


def test_project_set_classifications():
    """Test có thể gán classifications cho project"""
    project = Project(
        project_id="proj_test",
        name="Test Project",
        status=ProjectStatus.CREATED,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )

    classifications = {
        "uuid-1": "Person",
        "uuid-2": "Organization",
        "uuid-3": "Company"
    }
    project.node_classifications = classifications

    assert project.node_classifications == classifications
    assert len(project.node_classifications) == 3
    assert project.node_classifications["uuid-1"] == "Person"


def test_project_to_dict_includes_classifications():
    """Test to_dict() bao gồm node_classifications"""
    project = Project(
        project_id="proj_test",
        name="Test Project",
        status=ProjectStatus.CREATED,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        node_classifications={"uuid-1": "Person"}
    )

    data = project.to_dict()
    assert "node_classifications" in data
    assert data["node_classifications"] == {"uuid-1": "Person"}


def test_project_from_dict_reads_classifications():
    """Test from_dict() đọc được node_classifications"""
    data = {
        "project_id": "proj_test",
        "name": "Test Project",
        "status": "created",
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
        "node_classifications": {"uuid-1": "Person", "uuid-2": "Organization"}
    }

    project = Project.from_dict(data)
    assert project.node_classifications == {"uuid-1": "Person", "uuid-2": "Organization"}


def test_project_save_and_load_with_classifications(temp_projects_dir):
    """Test persist project với classifications"""
    project = ProjectManager.create_project("Test Project")
    project.node_classifications = {"node-1": "Person", "node-2": "Company"}
    ProjectManager.save_project(project)

    # Đọc lại từ disk
    loaded = ProjectManager.get_project(project.project_id)
    assert loaded is not None
    assert loaded.node_classifications == {"node-1": "Person", "node-2": "Company"}


def test_project_from_dict_without_classifications_defaults_none():
    """Test from_dict() không có classifications thì defaults là None"""
    data = {
        "project_id": "proj_test",
        "name": "Test Project",
        "status": "created",
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00"
    }

    project = Project.from_dict(data)
    assert project.node_classifications is None
