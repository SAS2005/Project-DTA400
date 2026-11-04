# IEEE Conference Paper Outline — DTA400 Network Simulation

**Target Format:** IEEE Conference Template (A4, Two-Column, 10-pt Times New Roman, 4 pages maximum including references)  
**Author of Individual Paper:** Shucayb Said (Simulation & experiments developed jointly with Firat Kaya)  
**Proposed Title:** *Dynamic Server Scaling: Performance and Cost Trade-Offs of Vertical, Horizontal, and Hybrid Autoscaling Under Variable Workloads*  
**University:** Department of Engineering Science, University West (*Högskolan Väst*), Trollhättan, Sweden

---

## Page Budget & Section Allocation (Target: Exactly 4.0 Pages)

| Section | Target Length | Key Contents & Visual Elements |
| :--- | :--- | :--- |
| **Title, Author Block, Abstract, Keywords** | ~0.30 page | Title, author affiliation, structured IMRaD abstract (~150 words), 6 IEEE Index Terms |
| **I. Introduction** | ~0.40 page | Problem context (variable web workloads, over/under-provisioning), scaling paradigms (vertical, horizontal, hybrid), explicit statement of **RQ1, RQ2, RQ3**, paper contributions |
| **II. Background and Related Work** | ~0.35 page | Cloud elasticity taxonomy, queuing theory ($M/G/1$ of capacity $c$ vs. $M/G/k$ of capacity $1$), reactive threshold autoscaling, cold-start latency and warm pooling |
| **III. Methodology and Simulation Design** | ~0.95 page | Five-component SimPy DES architecture, job size distribution ($\mathbb{E}[W]=0.13\text{ CPU-s}$), piecewise-Poisson traffic profiles (`Fig. 1`), scaling state machines & static baselines (`Table I`: single-server $1\times c$ vs. multi-server $k\times 1$), post-horizon drain phase & throughput accounting (arrival-window throughput vs. end-to-end completion rate), continuous-time normalized cost model, Common Random Numbers ($N=10$ seeds) & paired statistical evaluation |
| **IV. Experimental Results** | ~1.25 pages | **A. Baseline Strategy Comparison (RQ1):** `Table II` (mean, 95% CI, per-run SLO pass rates `10/10` vs `8/10`), `Fig. 2` (`fig06` capacity tracking), `Fig. 3` (`fig08` Cost–P95 trade-off).<br>**B. Cold-Start, Standby, and Shutdown Delay Sensitivity (RQ2):** `Fig. 4` (`fig09` startup delay $0..30\text{ s}$), `Fig. 5` (`fig10` warm standby and shutdown delay $30..120\text{ s}$).<br>**C. Multi-Scenario & Paired Statistical Comparison of Hybrid Regimes (RQ3):** `Table III` (paired differences $d_i$, 95% CI, statistical significance, and strict per-run vs. mean-P95 compliance). |
| **V. Discussion and Threats to Validity** | ~0.40 page | Step granularity ($1\text{ unit}$ vs. $2\text{ units}$) vs. single-request speedup ($W/c$), why paired CIs show Hybrid and Vertical are tied in raw cost but Hybrid breaks single-node vertical ceilings, threats to validity & limitations |
| **VI. Conclusion** | ~0.20 page | Concise empirical synthesis answering **RQ1, RQ2, and RQ3**, future work |
| **References** | ~0.15 page | 10 authentic IEEE-formatted references (`[1]`–`[10]`) |

---

## Figures & Tables Embedded in the 4-Page Paper

To fit cleanly within the **4-page IEEE conference limit (including references)** while presenting complete empirical evidence, the 4-page manuscript embeds **3 compact tables** and **5 high-density figures** (while the repository generates all 10 figures `fig01`–`fig10` for full inspection):

1. **Table I:** Scaling Strategy Configurations, Static Baselines ($1\times c$ vs. $k\times 1$), and Autoscaler Parameters.
2. **Table II:** Experiment 1 Summary Metrics (`variable_baseline`, $N=10$ seeds, Mean $\pm 95\%$ CI, Arrival-Window vs. End-to-End Throughput, and Per-Run SLO Compliance at $1.0\text{ s}$ and $0.35\text{ s}$).
3. **Table III:** Paired Seed-by-Seed Statistical Comparisons ($d_i = x_{A,i} - x_{B,i}$, Mean Diff, 95% CI, Significance) and RQ3 Regime Winners.
4. **Fig. 1 (`fig01_workload_over_time.png`):** Variable baseline workload arrival rate $\lambda(t)$ and empirical arrivals.
5. **Fig. 2 (`fig06_available_capacity_over_time.png`):** Provisioned active processing capacity over time vs. mean CPU demand $\lambda(t)\mathbb{E}[W]$.
6. **Fig. 3 (`fig08_cost_vs_response_time_tradeoff.png`):** Operating Cost vs. P95 Response Time Pareto trade-off chart.
7. **Fig. 4 (`fig09_cold_start_impact.png`):** Effect of provisioning startup delay ($0\text{ s}–30\text{ s}$) on P95 latency under baseline and sudden-spike workloads.
8. **Fig. 5 (`fig10_standby_and_shutdown_sensitivity.png`):** Warm standby impact (Panel A) and scale-down observation delay sensitivity (Panel B) under recurring spikes.
