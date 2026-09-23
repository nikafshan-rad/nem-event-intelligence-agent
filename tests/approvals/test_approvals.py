"""G5: local case-note approval boundary (mock reviewers; nothing leaves data/case_notes)."""

from __future__ import annotations

import pytest

from nem_agent.approvals import ApprovalError, CaseNoteStore, canonical_hash

pytestmark = pytest.mark.synthetic
CONTENT = {"headline": "SYNTHETIC note content for approval tests", "observations": [1, 2, 3]}


@pytest.fixture
def store(tmp_path):
    return CaseNoteStore(tmp_path / "notes")


def test_no_approval_no_write(store):
    p = store.propose(CONTENT, author="analyst-1")
    with pytest.raises(ApprovalError, match="no approval"):
        store.publish(p.proposal_id, None)
    assert store.notes() == []


def test_self_approval_rejected(store):
    p = store.propose(CONTENT, author="mock-reviewer-a")
    with pytest.raises(ApprovalError, match="self-approval"):
        store.approve(p.proposal_id, "mock-reviewer-a", p.content_sha256)
    assert store.notes() == []


def test_unknown_reviewer_and_wrong_hash_rejected(store):
    p = store.propose(CONTENT, author="analyst-1")
    with pytest.raises(ApprovalError, match="allowlisted"):
        store.approve(p.proposal_id, "random-person", p.content_sha256)
    with pytest.raises(ApprovalError, match="does not match"):
        store.approve(p.proposal_id, "mock-reviewer-a", canonical_hash({"other": 1}))
    assert store.notes() == []


def test_stale_approval_rejected_after_revision(store):
    p = store.propose(CONTENT, author="analyst-1")
    a = store.approve(p.proposal_id, "mock-reviewer-a", p.content_sha256)
    store.revise(p.proposal_id, {**CONTENT, "headline": "changed after approval"}, author="analyst-1")
    with pytest.raises(ApprovalError, match="stale"):
        store.publish(p.proposal_id, a.approval_id)
    assert store.notes() == []


def test_valid_distinct_approval_writes_exactly_once(store):
    p = store.propose(CONTENT, author="analyst-1")
    a = store.approve(p.proposal_id, "mock-reviewer-b", p.content_sha256)
    first = store.publish(p.proposal_id, a.approval_id)
    second = store.publish(p.proposal_id, a.approval_id)          # duplicate application of the same approval
    a2 = store.approve(p.proposal_id, "mock-reviewer-a", p.content_sha256)
    third = store.publish(p.proposal_id, a2.approval_id)          # second approval of the same content
    assert first["status"] == "written"
    assert second["status"] == third["status"] == "already_published"
    notes = store.notes()
    assert len(notes) == 1 and notes[0]["content_sha256"] == p.content_sha256 and notes[0]["reviewer"] == "mock-reviewer-b"


def test_approval_for_other_proposal_rejected(store):
    p1 = store.propose(CONTENT, author="analyst-1")
    p2 = store.propose({**CONTENT, "x": 2}, author="analyst-1")
    a1 = store.approve(p1.proposal_id, "mock-reviewer-a", p1.content_sha256)
    with pytest.raises(ApprovalError, match="different proposal"):
        store.publish(p2.proposal_id, a1.approval_id)
    assert store.notes() == []
