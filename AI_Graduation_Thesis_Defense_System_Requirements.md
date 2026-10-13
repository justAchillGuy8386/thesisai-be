# ThesisAI — Implementation Specification for AI Coding Agents

**Version:** 3.0  
**Purpose:** Graduation-thesis MVP; free/local-first; primary user is the student.  
**Status:** Implementation guide. Agents must inspect the actual repository before changing code.

## 1. Product goal

ThesisAI is a web application for managing graduation-thesis projects and helping students prepare for their defense. Thesis management is a supporting function; the core differentiator is AI-supported, document-grounded defense practice.

This is a practice tool, not an official university grading system. Scores must be labelled as estimates.

### MVP priorities
1. Upload thesis materials and extract usable content.
2. Build a project-specific knowledge profile and retrieval index.
3. Generate relevant questions grounded in the uploaded materials.
4. Let students answer by speaking, with a separate recording per question.
5. Process answers asynchronously while the student continues to later questions.
6. Produce a final evidence-based report after all required jobs finish or fail explicitly.
7. Prefer free/open-source/local components. Do not introduce paid services without approval.

## 2. Stack direction

- **Frontend:** Next.js App Router, TypeScript, Tailwind CSS, optionally shadcn/ui.
- **Backend:** Python + FastAPI.
- **Database:** PostgreSQL; pgvector for embeddings if practical in the current repository/environment.
- **Parsing:** PyMuPDF for PDF, python-docx for DOCX, python-pptx for PPTX.
- **Speech-to-text:** Whisper or faster-whisper, selected after testing compatibility and speed.
- **LLM:** local model through Ollama or a similar local inference server, using a model small enough for available hardware.
- **Embeddings:** local embedding model suitable for Vietnamese/technical text.
- **Audio analysis:** librosa and/or Parselmouth only for measurable, defensible features.
- **Queue:** start with a simple background worker if sufficient; add Redis + Celery/RQ only when reliability requires it. Avoid multiple queue systems.
- **Storage:** local filesystem for MVP, outside the public web root; audio/document binaries do not belong in PostgreSQL.
- **Development:** local-first; Docker Compose is optional if it simplifies setup.

Developer machine: 16 GB RAM, Ryzen 7 8745H, integrated Radeon 780M. Treat this as a development/small-demo machine, not a high-throughput inference server. Limit worker concurrency and benchmark actual model memory/runtime. Integrated graphics shares system memory and may not accelerate every AI library.

**Out of MVP scope by default:** paid cloud, paid AI APIs, GPU instances, Kubernetes, autoscaling, multi-region deployment. AWS can be considered later only if needed for the demo and approved.

## 3. Roles and management functions

### Student — primary
- Create/view their thesis project and topic.
- Upload proposal, thesis report, and supporting materials.
- Start a practice session.
- Record answers, view processing status, replay audio, and view report.
- Understand document/session effects when replacing or deleting files.

### Lecturer — secondary
- View supervised students.
- Review/approve thesis topics and submitted reports/documents.
- View basic project status.

Admin/user management is optional if not necessary for a working demonstration. Do not let management screens displace the core AI practice workflow.

## 4. Conceptual data model

Adapt names to the existing codebase; use migrations, foreign keys, indexes, and explicit status transitions.

- **User:** id, name, login identifier, role (`student`, `lecturer`, optional `admin`), timestamps.
- **ThesisProject:** id, student_id, title, topic, description, status, timestamps.
- **Document:** id, project_id, original_filename, mime_type, storage_path, file_size, content hash/version, processing_status, error_message, timestamps.
- **DocumentChunk:** id, document_id, project_id, chunk_index, section_title, page_number/slide_number, text, embedding, timestamps.
- **ProjectKnowledgeProfile:** id, project_id, version, profile_json, source_document_ids, status, timestamps.
- **PracticeSession:** id, project_id, mode (`question_answer`, `full_presentation`), status, knowledge_profile_version, started_at, ended_at.
- **Question:** id, session_id, order_index, question_text, difficulty, topic/competency, expected_answer_outline/rubric, source_chunk_ids, recommended_seconds (default 120).
- **Answer:** id, question_id, audio_path, audio_mime_type, duration_seconds, transcript, transcript_segments, processing_status, error fields, timestamps.
- **AnswerEvaluation:** id, answer_id, content_score, optional delivery_score, overall_score, criterion_scores_json, feedback_json, evidence_json, model_metadata_json.
- **PresentationSlideEvent:** id, session_id, slide_index, event_type, elapsed_ms.
- **ProcessingJob (if needed):** id, session_id, answer_id/chunk_id, job_type, status, attempt_count, timestamps, error_code.

Do not store uploaded files or audio blobs directly in PostgreSQL unless there is a strong documented reason.

## 5. Document ingestion and knowledge profile

### Initial supported types
PDF, DOCX, PPTX. Validate extension, MIME/content, and size. Reject unsupported/corrupt files with a useful message. Never use the raw supplied filename as a storage path.

### Pipeline
1. Store file securely and create metadata.
2. Extract text/structure, preserving PDF page and PPTX slide numbers where possible.
3. Detect empty/scanned content; use OCR selectively for scanned pages only.
4. Split text into semantically useful chunks with document/page/slide/section provenance.
5. Batch-generate embeddings if vector retrieval is enabled.
6. Build/update a concise project knowledge profile.
7. Mark the document `ready` only when required processing is complete; otherwise `failed` with safe error information.

Profile fields, when supported by sources: topic/problem, motivation/goals, scope, methods, architecture, technologies and rationale, data model/API, implementation, tests/evaluation, results, limitations/future work, and unknown/missing information.

### Performance and grounding
- Do not put a whole large document set into one LLM prompt.
- Process files in parallel only within a configured limit; batch embeddings and cache by file hash/version.
- Use the profile for overview and retrieval for detailed evidence.
- Retrieval must be scoped to the current project and include source references.
- Never invent facts that are not supported by the uploaded material; mark them unknown/unsupported.
- Show truthful progress/status; do not claim readiness before work completes.

## 6. Mode A — Question-and-answer practice (core feature)

### Session preparation
- Require at least one successfully processed document.
- Use the project knowledge profile and relevant source chunks.
- Generate **about 12–15 questions** when the available material supports that many; do not force the count when source content is too limited.
- Progress from easy/basic comprehension to medium and hard/advanced reasoning.
- Avoid near-duplicates and save the question set/profile version for the session so it does not change silently mid-session.
- Each question includes text, difficulty, topic/competency, expected-answer outline/rubric, source references, and recommended speaking time (120 seconds).

Question topics may include problem, goals, methods, architecture, design decisions, implementation, testing/results, limitations, trade-offs, and future work—but only when relevant and supported by the project materials.

### Voice-first interaction
- Speech is the primary answer mode; typed answers are not the main workflow.
- Each question has its own microphone start/stop controls and audio file.
- Recording begins/ends only by user action; do not auto-stop at 2 minutes or 2 minutes 30 seconds.
- Show the recommended duration (120 seconds). After **150 seconds**, show a gentle “past recommended time” warning while recording continues.
- Ask for microphone permission only after the user initiates recording.
- Handle permission denial, silence, too-short recordings, unsupported audio formats, cancellation, upload interruption, and duplicate submission.
- Preserve original audio for playback.
- After the backend confirms an answer audio file is stored, let the student continue while transcription/evaluation runs in the background.

### Per-answer pipeline
1. Store audio and answer metadata.
2. Return an acknowledgment and processing status quickly.
3. Enqueue transcription/evaluation; do not keep the HTTP request open for long inference.
4. Transcribe with timestamps when supported.
5. Retrieve relevant thesis chunks using the question and transcript.
6. Evaluate against the question, rubric, and source evidence.
7. Analyze delivery only when measurements are meaningful.
8. Persist result and update status.
9. Retry transient errors safely; retries must not create duplicate answers/evaluations.

### Evaluation criteria
Content: technical correctness, relevance, completeness, reasoning, consistency with source documents, explanation of design choices/trade-offs, and limitations where relevant.

Possible measurable delivery features: speaking rate, pause duration/distribution, filler words when transcript quality permits, speech continuity/timing, and validated prosodic/intelligibility metrics.

Do not infer emotion, confidence, honesty, or knowledge from voice alone. A pause does not prove lack of knowledge; fast speech does not prove stress; monotone speech does not prove poor understanding.

### Scoring and report
- A starting configurable rubric may use 80% content / 20% delivery, but label it experimental, not scientifically validated.
- If delivery analysis is unavailable/unreliable, do not fabricate a score; report it as unassessed.
- Do not automatically penalize obvious STT mistakes. Preserve audio and flag uncertain transcript segments.
- Scores are practice estimates, not official grades.
- Per-question report: question, transcript, score, strengths, gaps, suggestions, source evidence, and audio playback.
- Overall report: estimated summary, content/delivery breakdown where available, failed/unassessed jobs, and recommended topics for another round.
- Final status must wait for all required jobs. If some jobs fail after retries, use `partial_failed` and identify missing results rather than silently omitting them.

## 7. Mode B — Full-presentation practice

This is a separate mode and should be implemented only after Mode A is stable if time is limited.

- Student uploads PPTX and presents for about 15–20 minutes.
- Prefer displaying slides inside ThesisAI with next/previous controls for the first version.
- Record one continuous presentation and log each slide change with slide index and elapsed session time.
- Do not auto-stop at a recommended duration.
- Upload/persist recording and process asynchronously.
- External PowerPoint screen-sharing, desktop capture, and automatic slide recognition are out of initial scope.

### Slide/audio alignment
- Use a common session clock for audio and slide-change events.
- Associate transcript timestamp segments with the active slide.
- Chunk processing at slide transitions only if the browser/container implementation is proven safe. Arbitrary `MediaRecorder` timeslice blobs may not be independently decodable.
- Either keep a continuous recording and process after recording, or use a tested chunking strategy that preserves/reconstructs the original recording.
- Never lose the original recording if a derived chunk fails.
- Final evaluation must be holistic; do not simply average per-minute scores.

Assess, where evidence supports it: coverage of problem/goals/method/design/implementation/results/conclusion/limitations, logical structure, transitions, whether speech elaborates rather than merely reads slides, consistency with slides and thesis documents, timing, and measurable delivery characteristics.

## 8. Jobs, queueing, and concurrency

This MVP is about reliability, not massive scale.

- Keep API handlers short; use background jobs for STT and LLM evaluation.
- Track states explicitly: `queued`, `running`, `succeeded`, `failed`, `retrying`.
- Bound concurrency according to RAM/VRAM and measured throughput.
- A queue lets jobs wait; it does not create compute capacity.
- Make jobs idempotent; retry transient failures with backoff, not invalid input forever.
- Recover stale jobs after worker restart and persist results before marking success.
- The final report waits for all required jobs or clearly reports partial failure.
- Start with one worker and low concurrency on the developer's 16 GB RAM machine. Serialize model-heavy work if RAM pressure requires it.
- Measure runtime, peak memory, queue depth, and failure rate before increasing concurrency.

Scaling API, DB, object storage, STT workers, and LLM workers separately is a future option. Large-scale 1,000-user load is not an MVP acceptance criterion.

## 9. Optional GitHub integration

Not required for the first working MVP. If added later:
1. Use explicit authorization and least-privilege read-only access.
2. Read README, repository tree, dependency manifests, configuration templates, API definitions, data models, and selected important source files.
3. Build a concise codebase profile linked to the thesis project profile.
4. Ground questions in source files and thesis documents with evidence.
5. Consider build/test execution only later in isolated sandboxes.

Never store GitHub credentials in plaintext, run repository code on the main API server, inject secrets into untrusted code, or publish/deploy without explicit consent. GitHub MCP is optional; read-only GitHub API/App integration is sufficient for an initial version.

## 10. Security and privacy

- Enforce project-level authorization on every document/audio/session/report request.
- Validate file type, size, and content; generate storage names; store files outside the public web root.
- Do not commit `.env`, tokens, credentials, thesis documents, audio, or private data.
- Avoid logging full transcripts/document contents by default.
- Provide safe deletion and define effects on chunks and existing reports.
- Do not expose stack traces or filesystem paths to users.
- Use parameterized DB queries/safe ORM patterns.
- Disclose clearly if any external AI provider receives document/audio content; do not introduce external processing without project-owner approval.
- Pin dependencies and document setup.

## 11. Failure cases

Implement useful status, safe messages, and retry paths where appropriate for:
- Unsupported/corrupt/password-protected/empty document
- Scanned PDF with no extractable text
- OCR/extraction/embedding/profile failure
- Insufficient evidence for question generation
- Microphone denied, silence, invalid audio, upload interruption
- Duplicate submission
- STT errors or low-quality transcript
- Local model unavailable/timeout
- Worker crash/restart
- Retry exhaustion
- User leaves and returns during processing
- One answer fails while others succeed
- Report requested before jobs finish
- Source file deleted while a job references it

## 12. UI status language

Suggested internal states and Vietnamese labels:

| State | UI label |
|---|---|
| `uploaded` | Đã tải lên |
| `extracting` | Đang đọc tài liệu |
| `indexing` | Đang chuẩn bị dữ liệu |
| `ready` | Sẵn sàng |
| `queued` | Đang chờ xử lý |
| `transcribing` | Đang chuyển giọng nói thành văn bản |
| `evaluating` | Đang đánh giá câu trả lời |
| `completed` | Hoàn tất |
| `partial_failed` | Hoàn tất một phần — có lỗi |
| `failed` | Xử lý thất bại |
| `cancelled` | Đã hủy |

Do not show fake percentages. If exact progress is unavailable, show a truthful stage label.

## 13. Tests and acceptance criteria

### Core acceptance
- Student can create/select a project and upload a supported document.
- Extraction status is visible and becomes `ready` or `failed`.
- Profile contains source-supported information only.
- System generates about 12–15 non-duplicate questions when the source supports them.
- Each question records a separate spoken answer.
- Recording never auto-stops at 120 or 150 seconds; warning appears after 150 seconds.
- Uploaded answers process in the background while student continues.
- Original audio can be replayed.
- Evaluation shows transcript, feedback, and source evidence where available.
- Final report waits for jobs and identifies partial failures.
- Unauthorized users cannot access other students' data.
- Setup instructions work on a clean environment.

### Test cases
- Unit tests for parsing, chunking, status transitions, scoring normalization, authorization.
- API tests for upload, session creation, answer submission, job status, report retrieval.
- Retry/idempotency tests.
- One normal PDF, DOCX, PPTX, and invalid/scanned input.
- Silence, invalid audio, interrupted upload, and unavailable-model cases.
- End-to-end session with a small local model or deterministic mock provider.
- Document tests that could not run because of hardware/model constraints.

A 1,000-user load test is not required for the graduation MVP. Test a small realistic concurrent load and report measured limits honestly.

## 14. Implementation phases

1. **Inspect repository:** tree, package files, backend dependencies, env examples, migrations, routes/components. Document actual state; do not rewrite from scratch.
2. **Project/documents:** models/migrations, secure uploads, local storage, PDF/DOCX/PPTX extraction, visible status.
3. **Knowledge profile/RAG:** chunking with source references, embeddings/retrieval if feasible, profile generation/cache.
4. **Voice Q&A:** session/questions, MediaRecorder, upload/playback, asynchronous STT/evaluation, status UI, final report.
5. **Reliability:** retries, idempotency, authorization, deletion, tests, resource measurements.
6. **Full presentation:** PPTX viewer, slide timestamps, continuous recording, transcript/slide alignment, holistic evaluation.
7. **Optional:** GitHub profile, lecturer workflow polish, advanced delivery analysis, cloud deployment if actually required.

## 15. Instructions to AI coding agents

Before coding:
1. Inspect the actual repository and report its current structure and stack.
2. Identify existing features and reuse them.
3. Compare repository state against this spec; list discrepancies and propose a minimal path.
4. Do not overwrite working code or invent file paths without inspection.
5. Do not add paid services, API keys, GPU instances, Kubernetes, or external dependencies without explaining the need and obtaining approval.
6. Keep changes incremental and runnable.
7. Add/update tests for changed behavior.
8. Update `.env.example` and setup docs without placing real secrets there.
9. At the end of each step, report files changed, features completed, commands/tests and results, limitations, and next step.

### Coding principles
- Keep route handlers thin; put business logic in services.
- Use typed request/response schemas and consistent naming.
- Keep model/provider integrations behind interfaces.
- Do not swallow exceptions silently.
- Avoid premature abstraction/optimization.
- Include loading, error, and empty UI states.
- Never fabricate success or AI progress.

### MVP definition of done
A student can upload thesis materials, wait for processing, generate grounded questions, record a separate spoken answer per question, continue while earlier answers process asynchronously, and receive a final practice report with audio playback, evidence, and honest error handling.

Mode A is the priority. Full-presentation mode and GitHub integration must not delay a reliable core question-and-answer workflow.

## 16. Decisions agents must confirm after repository inspection

- Existing auth and role enforcement
- Current DB/migration tooling
- A local LLM and embedding model that fit 16 GB RAM
- pgvector vs simpler local vector index
- Whether a durable queue is necessary at demo scale
- Audio encoding/normalization strategy supported by target browsers
- Upload and recording limits
- Whether Mode B fits the remaining thesis timeline

Choose the simplest reliable free/local-first option, document trade-offs, and ask before introducing recurring costs.
