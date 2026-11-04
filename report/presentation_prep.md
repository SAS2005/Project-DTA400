# Oral Presentation & Examination Preparation Guide (DTA400)

**Project Title:** Dynamic Server Scaling: Performance and Cost Under Variable Workloads  
**Project Members:** Shucayb Said & Firat Kaya  
**Course:** DTA400 – Network Simulation, University West (Autumn 2026)

---

## 1. What Was Simulated? (Elevator Pitch)

We built a reproducible **discrete-event simulation (DES)** in Python and SimPy that models a cloud-hosted web application serving time-varying HTTP request traffic. We simulated:
- **Stochastic client traffic** arriving via a non-homogeneous Poisson process with three request classes (`small`: $0.05\text{ CPU-s}$ at $50\%$, `medium`: $0.15\text{ CPU-s}$ at $35\%$, `heavy`: $0.35\text{ CPU-s}$ at $15\%$; mean work $\mathbb{E}[W] = 0.13\text{ CPU-s}$).
- **A centralized FIFO waiting queue** and **a dynamic pool of server instances** with five lifecycle states (`STOPPED`, `BOOTING`, `ACTIVE`, `DRAINING`, `STANDBY`).
- **A reactive threshold-based autoscaler** that monitors server utilization and queue length every $5.0\text{ s}$ and compares **Vertical Scaling**, **Horizontal Scaling**, and **Hybrid Scaling** against static single-server baselines (`static_1`: $1\times 1$, `static_2`: $1\times 2$, `static_4`: $1\times 4$) and horizontal multi-server static baselines (`static_horizontal_2`: $2\times 1$, `static_horizontal_4`: $4\times 1$) across $N = 10$ independent random seeds (`42..51`).

---

## 2. Why Was Python + SimPy Chosen Instead of ns-3?

- **Abstraction Level Match:** Packet-level simulators like `ns-3` model TCP/IP headers, link-layer queues, and routing protocols at microsecond timescales. Our research questions (RQ1–RQ3) investigate **application-level queuing, server capacity provisioning, cold-start delays ($5–30\text{ s}$), warm standby states, and hourly operating costs** over 1-hour horizons ($\sim 23,000–28,000$ requests per run).
- **Event-Driven Precision:** SimPy is a process-based discrete-event simulation framework where simulation time jumps directly from one exact event timestamp to the next (e.g., request arrival, job completion, boot completion, autoscaler check). This allows us to run **340+ full 1-hour simulations across 10 seeds in under 15 seconds** with exact continuous-time integral accounting.
- **Course Compliance:** The DTA400 course guidelines explicitly permit custom discrete-event simulation programs for server, queue, load-balancing, and performance studies, and our proposal using Python/SimPy was formally approved.

---

## 3. How the Five Architectural Components Work

1. **Traffic Generator (`workload.py`):**
   - Uses a seeded `numpy.random.Generator` to pre-generate request arrival timestamps and job sizes before the simulation starts.
   - **Key Technical Detail:** In a piecewise-constant Poisson process, if arrival rate $\lambda(t)$ jumps at a segment boundary (e.g., $t = 2100\text{ s}$ from $12\text{ req/s}$ to $20\text{ req/s}$ in `variable_baseline`, or $t = 1200\text{ s}$ from $6\text{ req/s}$ to $22\text{ req/s}$ in `sudden_spike`), a naive loop might sample an inter-arrival time across the boundary using the old rate. Our generator strictly truncates inter-arrival sampling at every segment boundary (using the memoryless property of the exponential distribution) so rate changes take effect instantaneously at segment boundaries.
   - **Common Random Numbers (CRN):** `clone_workload()` replays the *exact same request stream* for a given seed across all strategies so any difference in latency or cost can be evaluated using **paired seed-by-seed differences** ($d_i = x_{A,i} - x_{B,i}$).

2. **Request Queue (`server.py` – `RequestQueue`):**
   - Stores waiting requests in strict FIFO order.
   - Computes the **exact continuous-time integral** of queue length $\int Q(t)\,dt$: every time a request enters or leaves the queue at time $t$, we add $Q_{\text{prev}} \times (t - t_{\text{last}})$ to `area_queue_time`. Dividing by total elapsed simulation time gives the exact time-weighted average queue length.

3. **Server Pool (`server.py` – `ServerPool` & `ServerInstance`):**
   - Each server has a capacity $c \in \{1, 2, 4\}$. A request with work $W$ takes $t_{\text{service}} = W / c$ seconds.
   - **Synchronous Dispatch Locking:** When `dispatch()` pops a request from the FIFO queue and assigns it to an idle `ACTIVE` server, `server.busy = True` is set synchronously before yielding to SimPy, preventing two simultaneous events at the exact same timestamp from double-booking a server.
   - **Safe Scale-Down (No Dropped Jobs):** If the autoscaler scales down a busy server, its state becomes `DRAINING`. It stops accepting new requests from the queue, finishes its current request normally, and only then transitions to `STANDBY` or `STOPPED`. Zero requests are ever dropped or aborted.

4. **Autoscaler (`scaling.py` – `Autoscaler`):**
   - Runs every $5.0\text{ s}$ (`monitoring_interval = 5.0 s`) up to $t = 3600\text{ s}$.
   - **Scale-up rule:** Triggered if rolling utilization $\ge 0.85$ (`scale_up_utilization_threshold = 0.85`) OR waiting queue length $\ge 2$ (`scale_up_queue_threshold = 2`) continuously for $2$ consecutive checks ($10.0\text{ s}$, `sustained_queue_samples = 2`).
   - **Scale-down rule:** Triggered if rolling utilization $\le 0.35$ (`scale_down_utilization_threshold = 0.35`) over the $60.0\text{ s}$ observation window (`scale_down_observation_window = 60.0 s`) AND waiting queue length $== 0$.
   - **Cooldown:** $60.0\text{ s}$ (`scaling_cooldown = 60.0 s`) after any scaling action completes to prevent oscillation ("thrashing").

5. **Metrics, Post-Horizon Drain Phase & Cost Collector (`metrics.py` – `MetricsCollector`):**
   - Request arrivals occur strictly in $[0, T_{\text{sim}})$ where $T_{\text{sim}} = 3600\text{ s}$. Any requests still queued or in service at $T_{\text{sim}}$ are served to completion during a post-arrival drain phase ($T_{\text{elapsed}} = T_{\text{sim}} + T_{\text{drain}}$), ensuring `completed_requests == generated_requests`.
   - Distinguishes **arrival-window throughput** ($N_{\text{completed, } t \le T_{\text{sim}}} / T_{\text{sim}}$) from **end-to-end completion rate** ($N_{\text{completed}} / T_{\text{elapsed}}$), preventing saturated runs with long post-horizon drain phases (e.g., `static_1` draining until $t \approx 3605–3630\text{ s}$) from inflating throughput above the arrival rate.
   - Integrates active capacity-seconds, provisioning capacity-seconds, standby capacity-seconds, and busy CPU-seconds over the full elapsed simulation time $T_{\text{elapsed}}$ (including any post-horizon drain phase).
   - Normalizes cost so **$1\text{ active capacity unit for } 1\text{ hour} = 1.00\text{ cost unit}$**, provisioning overhead $= 1.00\text{ unit/cap-hr}$, and warm standby $= 0.25\text{ unit/cap-hr}$.

---

## 4. How the Scaling Strategies Work & Why the Comparison Is Fair

All dynamic strategies are constrained between **$C_{\min} = 1\text{ unit}$ and $C_{\max} = 4\text{ units}$** and use the **exact same autoscaler thresholds**:

- **Vertical (`vertical`):** 1 server whose capacity scales $1 \leftrightarrow 2 \leftrightarrow 4$ ($5.0\text{ s}$ live resize delay). During a $5.0\text{ s}$ upgrade, the server keeps running at its current capacity while the delta $\Delta c$ is charged as provisioning overhead.
- **Horizontal (`horizontal`):** $1 \leftrightarrow 2 \leftrightarrow 3 \leftrightarrow 4$ servers, each of capacity $1$ ($10.0\text{ s}$ cold boot, or $2.0\text{ s}$ warm resume from `STANDBY`).
- **Hybrid (`hybrid`):** Starts with $1\times 1$ ($1\text{ unit}$) $\leftrightarrow$ vertically upgrades to $1\times 2$ ($2\text{ units}$, $5\text{ s}$ delay) $\leftrightarrow$ horizontally scales out to $2\times 2$ ($4\text{ units}$, $10\text{ s}$ cold / $2\text{ s}$ warm delay).
- **Adaptive Hybrid (`hybrid_adaptive`):** Adds an intermediate 3-unit state: $[1] \leftrightarrow [2] \leftrightarrow [2, 1] \leftrightarrow [2, 2]$.
- **Static Baselines:** `static_1` ($1\times 1$), `static_2` / `static_vertical_2` ($1\times 2$), and `static_4` / `static_vertical_4` ($1\times 4$) are single-server vertical baselines; `static_horizontal_2` ($2\times 1$) and `static_horizontal_4` ($4\times 1$) provide multi-server horizontal static baselines.

---

## 5. Key Findings to Present for RQ1, RQ2, and RQ3

### RQ1: Lowest Cost While Meeting the Response-Time SLO ($\text{P95} \le 1.0\text{ s}$)
- **Result:** On the 1-hour `variable_baseline` workload, **Horizontal scaling achieves the lowest cost ($1.9789 \pm 0.0242\text{ units}$, P95 $= 0.3907\text{ s}$, 10/10 runs compliant)**, saving **50.5%** vs. `static_4` ($4.00\text{ units}$).
- **Paired Statistical Evidence:** Across all 10 seeds, Horizontal is significantly cheaper than Vertical ($\bar{d} = -0.1440\text{ units}$, 95% CI $[-0.1730, -0.1151]$, $-6.78\%$) and 3-tier Hybrid ($\bar{d} = -0.1371\text{ units}$, 95% CI $[-0.1668, -0.1074]$, $-6.48\%$). Compared with `hybrid_adaptive` ($2.0110\text{ units}$), Horizontal's mean cost is $1.60\%$ lower ($\bar{d} = -0.0321\text{ units}$), though the paired 95% CI $[-0.0730, +0.0089]$ includes zero.
- **Why?** During the 10-minute High-load phase ($1500–2100\text{ s}$, $\lambda = 12\text{ req/s}$, mean demand $1.56\text{ units}$), Horizontal steps to **3 units ($3\times 1$)** ($52\%$ utilization), whereas binary Vertical ($1 \to 2 \to 4$) and 3-tier Hybrid ($1\times 1 \to 1\times 2 \to 2\times 2$) must jump directly from $2$ to **4 units**.
- **Latency trade-off:** Vertical ($\text{P95} = 0.3256\text{ s}$, $\text{Avg} = 0.0982\text{ s}$) and Hybrid ($\text{P95} = 0.3321\text{ s}$, $\text{Avg} = 0.1090\text{ s}$) achieve **33%–40% lower mean response time** and **15%–17% lower P95 response time** than Horizontal ($\bar{d}_{\text{P95}} = -0.0650\text{ s}$ and $-0.0586\text{ s}$, both statistically significant) because higher per-server capacity ($c \ge 2$) executes individual jobs $2\times$ to $4\times$ faster.

### RQ2: Effect of Startup Delays, Warm Standby, and Delayed Shutdown
- **Startup Delay ($0..30\text{ s}$, Fig. 9):** During a sudden spike ($6 \to 22\text{ req/s}$), Horizontal violates the $1.0\text{ s}$ SLO when cold-start delay reaches $20\text{ s}$ ($\text{P95} = 1.15\text{ s}$, $1/10$ runs compliant) and hits **$\text{P95} = 3.78\text{ s}$ at $30\text{ s}$ delay** ($0/10$ runs compliant), because it must scale one server at a time ($2 \to 3 \to 4$). Vertical ($\text{P95} = 0.90\text{ s}$, $9/10$ runs compliant) and Hybrid ($\text{P95} = 0.90\text{ s}$, $9/10$ runs compliant) jump from $2 \to 4$ units in a single step.
- **Warm Standby (Fig. 10a):** Under recurring spikes with $\text{SD} = 30\text{ s}$, turning on warm standby ($2\text{ s}$ resume at $25\%$ cost) cuts Horizontal P95 latency by **79.4%** ($2.60\text{ s} \to 0.53\text{ s}$, restoring $10/10$ SLO compliance) and Hybrid P95 by **66.9%** ($6.48\text{ s} \to 2.14\text{ s}$) for $+11\%–12\%$ cost. On non-bursty workloads (`variable_baseline`), standby adds $\sim 9\%–11\%$ cost with zero latency benefit.
- **Shutdown Delay ($30\text{ s}, 60\text{ s}, 120\text{ s}$, Fig. 10b):** Under recurring spikes with $45\text{ s}$ lulls, a $30\text{ s}$ shutdown window causes premature scale-down and severe SLO violations across all strategies ($\text{P95} = 1.36–5.13\text{ s}$, $0/10$ compliant). Extending the window to **$60\text{ s}$** bridges the $45\text{ s}$ lulls and restores $10/10$ (100%) SLO compliance ($\text{P95} = 0.38–0.52\text{ s}$) for only **$+4.0\%–6.3\%$ cost**.

### RQ3: When Is Hybrid Scaling More Cost-Effective Than Vertical or Horizontal Alone?
1. **Strict Latency SLOs ($\text{P95} \le 0.35\text{ s}$ on `variable_baseline`):**
   - Horizontal fails in **all 10/10 runs** ($\text{P95} = 0.3907\text{ s}$, min seed $0.3770\text{ s}$) because a capacity-1 server requires $0.35\text{ s}$ of pure service time just to execute a single Heavy job ($0.35\text{ CPU-s}$).
   - **Mean-P95 Feasibility vs. Strict 100% Per-Run Compliance:** Under a **mean-P95 criterion** ($\overline{\text{P95}} \le 0.35\text{ s}$), `hybrid_adaptive` ($2.0110\text{ units}$, $\overline{\text{P95}} = 0.3467\text{ s}$) is significantly cheaper than both `hybrid` ($2.1160\text{ units}$, $\bar{d} = -0.1050$, 95% CI $[-0.1630, -0.0470]$) and `vertical` ($2.1229\text{ units}$), but satisfies $\text{P95} \le 0.35\text{ s}$ in **8 of 10 runs (80%)** (two seeds hit $0.35001\text{ s}$). Under **strict 100% per-run compliance (10/10 seeds)**, only `hybrid` ($\max\text{P95} = 0.3469\text{ s}$) and `vertical` ($\max\text{P95} = 0.3405\text{ s}$) qualify; their cost difference is statistically indistinguishable ($\bar{d} = -0.00694\text{ units}$, 95% CI $[-0.01462, +0.00074]$, includes zero).
2. **Sudden Isolated Traffic Spikes (`sudden_spike`):** Both `hybrid` ($1.8185\text{ units}$) and `vertical` ($1.8221\text{ units}$) are **statistically significantly cheaper than `horizontal` ($1.8443\text{ units}$)** ($\bar{d}_{\text{hyb}-\text{hor}} = -0.02582\text{ units}$, 95% CI $[-0.04084, -0.01079]$, $-1.40\%$) while achieving $23\%$ lower P95 latency ($0.3779\text{ s}$ vs. $0.4912\text{ s}$), because they scale down from 4 to 2 units in one step after the spike instead of stepping through 3 units. However, the tiny $0.00361\text{ unit}$ ($-0.20\%$) difference between `hybrid` and `vertical` has a paired 95% CI of $[-0.00839, +0.00117]$ that includes zero, so `hybrid` and `vertical` are statistically tied in cost.
3. **Per-Server Vertical Ceiling ($c_{\max,\text{node}} = 2$):** When a single machine cannot scale vertically beyond 2 units (`static_2` fails with $\text{P95} = 21.43\text{ s}$), pure vertical scaling cannot reach 4 units, whereas `hybrid` ($2\times 2$) and `hybrid_adaptive` ($[2,1] \to [2,2]$) achieve **100% (10/10) compliance** at both $\text{P95} \le 1.0\text{ s}$ and $\text{P95} \le 0.35\text{ s}$ (for `hybrid`).

---

## 6. Main Limitations & Likely Examiner Q&A

**Q1: "What is the difference between `static_2`/`static_4` and horizontal static baselines?"**  
> **Answer:** In our simulator, `static_1` ($1\times 1$), `static_2` ($1\times 2$), and `static_4` ($1\times 4$) model a **single server** with capacity $c \in \{1, 2, 4\}$, whereas `static_horizontal_2` ($2\times 1$) and `static_horizontal_4` ($4\times 1$) model 2 or 4 independent servers of capacity 1. Because a single server of capacity $c$ executes individual requests $c$ times faster ($t_s = W/c$), `static_4` ($1\times 4$) achieves lower per-request service time than `static_horizontal_4` ($4\times 1$) even though both have identical total processing capacity ($4\text{ CPU-s/s}$) and identical hourly cost ($4.00\text{ units}$).

**Q2: "Why did you report both per-run SLO compliance and mean P95 across seeds?"**  
> **Answer:** Averaging P95 across 10 seeds can mask tail violations in individual runs. For example, under the strict $\text{P95} \le 0.35\text{ s}$ target on `variable_baseline`, `hybrid_adaptive` has a mean P95 of $0.3467\text{ s} \le 0.35\text{ s}$, but 2 of its 10 seeds marginally exceed $0.35\text{ s}$ ($80\%$ per-run compliance), whereas `hybrid` and `vertical` pass in all $10/10$ runs ($100\%$ compliance). Reporting both metrics prevents overstating reliability near an SLO boundary.

**Q3: "Why did you use paired confidence intervals when comparing strategy costs?"**  
> **Answer:** Because we use Common Random Numbers (`clone_workload()`), every strategy faces the exact same arrival stream for each seed $i \in \{42..51\}$. Computing paired differences $d_i = x_{A,i} - x_{B,i}$ removes inter-seed traffic variance and tests whether cost differences are genuine or random noise. This proved that while `hybrid` and `vertical` significantly beat `horizontal` on `sudden_spike` ($95\%$ CI excludes zero), the $0.0036\text{ unit}$ ($0.20\%$) difference between `hybrid` and `vertical` has a $95\%$ CI of $[-0.0084, +0.0012]$ that includes zero—meaning they are statistically tied.
