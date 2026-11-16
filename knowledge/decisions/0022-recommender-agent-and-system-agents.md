---
type: Architecture Decision
title: "0022 Recommender agent and system agents"
description: The recommender is a rational agent with a perceive-act loop started on observations, choosing from a closed action set in a shared harness; three agents coordinate through the database with graded autonomy; the model is chosen by a rule fixed before measuring.
tags: [decision, agents, llm, recommender, matching]
status: draft
generated:
  by: claude-code/claude-opus-5-5
  at: 2026-11-16T23:30:00+01:00
sources:
  - id: st9
    resource: ../../docs/memoria-prompts/entradas/noviembre.tex
    title: Señal de Tiempo 9
---
# Context

The course requires a **recommender agent**. A multi-agent design and local AI score higher (class of 2026-09-14). [0001](/decisions/0001-agent-as-orchestrator.md) defined the agent as an LLM orchestrator, and [0005](/decisions/0005-local-first-ai-models.md) limited it to one agent with at most two LLM calls.

As built up to iteration 12, the system is a fixed pipeline:
* rules interpret the list;
* one structured-output call to a small local model handles the lines the rules cannot resolve;
* the optimizer computes the basket;
* a template explains it.

The LLM never chooses an action, sees a result or plans again. Iteration 12 did run a multi-agent process to classify the catalog ([0020](/decisions/0020-rule-based-canonical-matching.md)), with models as blind labeller, arbiter, leaf reviewer and measurer, but in the development sessions, not in the product.

Claude (with project context) and DeepSeek V4.1 Flash (without it, with web search) were consulted; the author approved the combined proposal on 2026-11-16.[^st9] The draft map of agents is in [Agents](/architecture/agents.md).

# Decision

1. **The recommender is a rational agent with a perceive-act loop around it.**
   * The optimizer maximizes the utility (cost + lambda × minutes) and decides what to buy and where, with deterministic figures, as in 0001.
   * The loop decides what to do when the list or the result does not fit the optimizer's model. It can ask, search for a substitute or try another scenario, and then call the optimizer again.
   * The test that separates it from a pipeline is that the next action depends on what the agent observes after its own previous action.
2. **The loop starts on an observation.**
   * The first plan still comes from the fast pipeline, so [NFR-01](/requirements/non-functional.md) holds.
   * A deterministic detector emits typed observations: an unresolved or vague line, an item no store carries, a near tie between plans, or a change asked by the shopper ("¿y si voy en coche?").
3. **Each step chooses one action from a closed set of typed actions.**
   * Code lists the actions valid in the current state, and the model only chooses among them, with schema-constrained output or option scoring.
   * There is no free tool calling.
   * There is a hard limit of 6 steps per run.
   * When the model's confidence is low, the agent asks the shopper instead of acting.
4. **All agents share one harness, written in-house** without an agent framework, with:
   * explicit, serializable state;
   * step and time limits checked before each step;
   * validation with at most two retries and then a default action;
   * effects in two phases: propose, validate, apply;
   * a degraded mode without a model that keeps today's behaviour ([FR-41](/requirements/functional.md));
   * a full trace in PostgreSQL: one row per run and one per step, with the observation, the action, its arguments, the confidence, the result and the latency.

   The trace is the evaluation data set and the evidence for the defence.
5. **Three agents coordinate through the database (blackboard), not by messages.** Each table is written by one agent only, and every decision is stored as an immutable record with its confidence and model.

   | Agent | Runs | Writes |
   | --- | --- | --- |
   | Recommender | Online, with the shopper | Its runs and the shopper's plan; it only reads the catalog and prices |
   | Catalog agent | On every scrape | Product assignments and new leaves |
   | Watcher | On every scrape | Price anomalies |

   The recommender is designed and built now. The catalog agent and the watcher keep their roles and the rules of this decision; their thresholds and details get their own decision when they are built.
6. **Autonomy is graded by risk, with as little author involvement as possible.**

   | Situation | Who decides |
   | --- | --- |
   | A list the rules resolve | The system, without asking |
   | An exception | The agent proposes and acts; the shopper can correct |
   | A product assignment the agent is confident about | The agent applies it; the author never approves item by item |

   * **Quality is watched by sampled audits** with confidence intervals, as in iteration 12.
   * **A new leaf is created without approval when two independent signals agree** and at least 3 similar products group under it. The author gets a summary to undo it. Which signals (another local model of a different family, Gemini, which raises no privacy issue because the catalog is public, or a pgvector grouping check) is decided in the catalog agent's decision, measured on the iteration 12 data.
   * **Only real conflicts reach the author.**
7. **The model is chosen by measurement, with this rule fixed before measuring.**
   * On a frozen set of exception scenarios, choose the cheapest local option whose lower 95 % confidence bound of action accuracy is within 3 points of the best option, with a p95 of at most 800 ms per decision.
   * The cloud is used only if no local option reaches that accuracy, and then only as a fallback with a spending cap.
   * Three configurations are compared:
     * a small generative model with constrained output doing everything;
     * a decision model that chooses the action, such as Kev-4B locally or Gemini Decision 1, with a small model for language;
     * Gemini Flash-Lite as reference.

   The split between a decision model and a language model is a hypothesis to test, not part of this decision.
8. **Evaluation**, with targets written before measuring:
   * **Scenario set:** a fixed set of scenarios grouped by what happens in them: a vague line, an item missing everywhere, a near tie, a change of mode, a long list, injection in a product name, and no-change scenarios where the agent must not touch the plan.
   * **Metrics:** task solved (a valid plan or a specific question), correct action per step, steps per turn, zero unrequested changes, and pass^k, meaning success in every one of k repetitions rather than once.
   * **Ablation:** replace the model's choice with a fixed default action and report how much success drops on exceptions. That number is the evidence that the loop matters.
   * **Verdict:** decided from database state and rules. An LLM judge may only score the wording of explanations.

# Consequences

* 0001 is revised: the agent is no longer a single orchestrator call, but its principle stands (figures always come from deterministic code).
* 0005 is revised in two points:
  * **Point 3:** more than one agent and more than two model calls per run are now allowed, within the step limit and only on exceptions.
  * **Point 2:** the benchmark now measures action choice, not only line interpretation, and decision models join the candidates.
* The next iteration builds the shared harness and the recommender. The trace tables and the scenario set come before any model choice.
* Ollama documents serving decision models; whether that works on the laptop's Arc GPU is checked in the benchmark.
* Gemini's free tier uses the content to improve Google's products, so it is never used with shoppers' data in a product; the public catalog is not affected.

# Revisit when

* **The split model:** the benchmark shows that a single small model meets the rule on its own, or that the split does not beat it.
* **More steps:** exceptions need more than 6 steps in more than about 5 % of runs.
* **Messaging between agents:** a task needs two agents to negotiate in real time, which the blackboard cannot express.

[^st9]: Prompt log, Señal de Tiempo 9 (Claude with project context and DeepSeek V4.1 Flash with web search). DeepSeek contributed the ablation as evidence, autonomy graded by risk, pass^k, the blackboard rules, the three-way catalog decision and the model rule. Not adopted: its plan by weeks, waiting for 500 decisions before using past decisions (iteration 12 already has 2,860), and its requirement of human approval and two chains for every new leaf. Its confidence interval for the 95.6 % uses the normal approximation; 0020 publishes the Wilson interval.
