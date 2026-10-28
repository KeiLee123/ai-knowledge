#!/usr/bin/env python3
"""M10A fixture regression: no external dependencies, DB, Drive, or writes."""
import hashlib
import json
import tempfile
from pathlib import Path
from m10_candidate_intake_v1 import inspect_batch, main

SOURCE="BD_PNAP_APP149"
STAMP="20261026T011508Z"
RUN="20261026T011509Z"

def save(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data)+"\n")

def make(tmp, decision="CANDIDATE_NEW_VERSION", second=False):
    root=tmp/"source-monitor-staging"
    root.mkdir()
    sources=[SOURCE]+(["BD_PNAP_APP145"] if second else [])
    rows=[]
    files={}
    for sid in sources:
        run=root/"runs"/sid/RUN
        run.mkdir(parents=True)
        candidate=run/"APP149-candidate.pdf"
        candidate.write_bytes(("%PDF-fixture-"+sid).encode())
        sha=hashlib.sha256(candidate.read_bytes()).hexdigest()
        ref=root/"version-snapshots"/"current"/(sid+".json")
        save(ref,{"version_snapshot_store_version":1,"source_id":sid,
                  "snapshot":{"document_sha256":"a"*64,
                              "issue_date":"2020-01","revision_date":"2020-01"}})
        d=decision if sid==SOURCE else "NO_CHANGE"
        action={"CANDIDATE_NEW_VERSION":"STAGING_VALIDATION_REQUIRED",
                "NO_CHANGE":"NONE","REVIEW_REQUIRED":"EXCEPTION_REVIEW",
                "BLOCKED":"STOP"}[d]
        monitor={"version":"official-source-monitor-v1","source_id":sid,"decision":d,
                 "action":action,"candidate_downloaded":d=="CANDIDATE_NEW_VERSION",
                 "baseline_status":"DOCUMENT_CHANGED" if d!="NO_CHANGE" else "UNCHANGED",
                 "production_access":False,"production_write":False}
        if d=="CANDIDATE_NEW_VERSION":
            monitor.update({"candidate_path":str(candidate),"candidate_sha256":sha,
                "reference_path":str(ref),
                "qualification":{"method":"policy","policy_version":"official-source-version-policy-v1",
                                 "mode":"version_candidate","decision":d},
                "signals":{"authority_match":True,"document_code_match":True,
                           "official_host_match":True,"checksum_changed":True,
                           "normalized_content_changed":True,"metadata_changed":True,
                           "staging_validation_verified":False,"deterministic_release":False,
                           "previous_issue_date":"2020-01","previous_revision_date":"2020-01"}})
        log=run/"monitor-output.txt"
        log.write_text("START\n"+json.dumps(monitor)+"\nSTATUS: "+d+"\n")
        rows.append({"source_id":sid,"execution_status":"EXECUTION_SUCCESS",
                     "return_code":0,"decision":d,"action":action,
                     "candidate_downloaded":monitor["candidate_downloaded"],
                     "run_dir":str(run),"production_access":False,"production_write":False})
        files[sid]={"candidate":candidate,"log":log,"monitor":monitor,"ref":ref}
    summary=root/"batches"/STAMP/"summary.json"
    save(summary,{"version":"source-monitor-batch-v1","batch_timestamp":STAMP,
                  "git_branch":"staging","git_commit":"b"*40,
                  "source_ids":sources,"results":rows,"overall_status":"SUCCESS",
                  "production_access":False,"production_write":False})
    return root,summary,files

def status(root,summary):
    return inspect_batch(summary,state_root=root)["results"][0]["status"]

def main_test():
    with tempfile.TemporaryDirectory() as d:
        root,summary,items=make(Path(d))
        before={str(f):(f.read_bytes(),f.stat().st_mtime_ns)
                for f in root.rglob("*") if f.is_file()}
        out=inspect_batch(summary,state_root=root)
        assert out==inspect_batch(summary,state_root=root)
        assert out["results"][0]["status"]=="READY_FOR_STAGING_VALIDATION"
        assert out["results"][0]["candidate_id"].startswith(SOURCE+":")
        assert out["write_authorized"] is False
        assert before=={str(f):(f.read_bytes(),f.stat().st_mtime_ns)
                       for f in root.rglob("*") if f.is_file()}
        items[SOURCE]["candidate"].write_bytes(b"tampered")
        assert status(root,summary)=="BLOCKED"
    for decision in ("NO_CHANGE","REVIEW_REQUIRED","BLOCKED"):
        with tempfile.TemporaryDirectory() as d:
            root,summary,_=make(Path(d),decision)
            assert status(root,summary)==decision
    with tempfile.TemporaryDirectory() as d:
        root,summary,items=make(Path(d))
        record=json.loads(summary.read_text())
        record["results"][0]["decision"]="NO_CHANGE"
        save(summary,record)
        assert status(root,summary)=="BLOCKED"
    with tempfile.TemporaryDirectory() as d:
        root,summary,items=make(Path(d))
        items[SOURCE]["monitor"]["production_write"]=True
        items[SOURCE]["log"].write_text(json.dumps(items[SOURCE]["monitor"]))
        assert status(root,summary)=="BLOCKED"
    with tempfile.TemporaryDirectory() as d:
        root,summary,items=make(Path(d))
        ref=items[SOURCE]["ref"]
        record=json.loads(ref.read_text())
        record["snapshot"]["revision_date"]="2022-01"
        save(ref,record)
        assert status(root,summary)=="BLOCKED"
    with tempfile.TemporaryDirectory() as d:
        root,summary,items=make(Path(d),second=True)
        record=json.loads(summary.read_text())
        record["overall_status"]="PARTIAL_FAILURE"
        record["results"][0]={"source_id":SOURCE,"execution_status":"EXECUTION_FAILED",
            "return_code":1,"production_access":False,"production_write":False}
        save(summary,record)
        assert [r["status"] for r in inspect_batch(summary,state_root=root)["results"]]==[
            "EXECUTION_FAILED","NO_CHANGE"]
    with tempfile.TemporaryDirectory() as d:
        root,summary,items=make(Path(d))
        outside=Path(d)/"outside.pdf"
        outside.write_bytes(b"x")
        items[SOURCE]["candidate"].unlink()
        items[SOURCE]["candidate"].symlink_to(outside)
        assert status(root,summary)=="BLOCKED"
    print("M10A offline regression: PASS")

if __name__=="__main__":
    main_test()
