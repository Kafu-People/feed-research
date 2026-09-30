# Docs

Three layers of documentation, each answering a different question.

| | Answers | Read when |
| --- | --- | --- |
| **[architecture.md](architecture.md)** | The whole design, in one file | You want the complete picture in one sitting |
| **[architecture/](architecture/)** | What and why, per concept | You're reasoning about one part |
| **[development/](development/)** | Where the code goes and what it looks like | You're building |

`architecture.md` is the source of truth. `architecture/` is the same content decomposed —
if the two ever disagree, the single file wins.

---

## architecture/ — what and why

| | | |
| --- | --- | --- |
| [1 The idea](architecture/01-the-idea.md) | [7 Match](architecture/07-match.md) | [13 Cost](architecture/13-cost.md) |
| [2 Three layers](architecture/02-three-layers.md) | [8 Deliver](architecture/08-deliver.md) | [14 Invariants](architecture/14-invariants.md) |
| [3 Collect](architecture/03-collect.md) | [9 Feedback](architecture/09-feedback.md) | [15 Build order](architecture/15-build-order.md) |
| [4 Read](architecture/04-read.md) | [10 Journey](architecture/10-user-journey.md) | [16 Still open](architecture/16-open-questions.md) |
| [5 Group](architecture/05-group.md) | [11 Data model](architecture/11-data-model.md) | |
| [6 Judge](architecture/06-judge.md) | [12 Runtime](architecture/12-runtime.md) | |

Index with reading paths: [architecture/README.md](architecture/README.md).

## development/ — how it's built

| Foundation | Pipeline | Clients |
| --- | --- | --- |
| [1 Repo layout](development/01-repo-layout.md) | [5 Worker stages](development/05-worker-stages.md) | [8 Web app](development/08-web-app.md) |
| [2 Tech stack](development/02-tech-stack.md) | [6 AI layer](development/06-ai-layer.md) | [9 Mobile app](development/09-mobile-app.md) |
| [3 Database](development/03-database.md) | [7 API](development/07-api.md) | [10 Shared client code](development/10-clients-shared.md) |
| [4 Job queue](development/04-job-queue.md) | | |

| Operating | Plan |
| --- | --- |
| [11 Config](development/11-config.md) · [12 Testing](development/12-testing.md) · [13 Observability](development/13-observability.md) | [17 Milestones](development/17-milestones.md) |
| [14 Local dev](development/14-local-dev.md) · [15 Deployment](development/15-deployment.md) · [16 Security](development/16-security-compliance.md) | |
| [19 Backups](development/19-backups.md) | |

Index: [development/README.md](development/README.md).

---

## The four things that would make this fail

Collected from across the docs, because they're easy to miss reading section by section:

1. **Topics don't deduplicate.** If a million users produce 4M distinct topics instead of
   ~300k, matching stops being flat in users. → [13 Cost](architecture/13-cost.md)
2. **Novelty doesn't predict interest.** The entire ranking premise rests on it and it is
   unvalidated. → [6 Judge](architecture/06-judge.md)
3. **Clustering merges wrong things.** A wrong merge makes the app lie and silently
   disappears an event. → [5 Group](architecture/05-group.md)
4. **Matching is bad on hand-written lists.** No amount of AI expansion rescues that.
   → [15 Build order](architecture/15-build-order.md)
