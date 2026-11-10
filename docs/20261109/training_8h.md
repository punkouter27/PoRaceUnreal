# 8-hour training session (started 2026-11-09 21:25 UTC, session porace-3a)

Priority: Grandma (not raceable: blocks the roster and the tournament), then Matt's jog, then the dog's impratio-1 margin.
GPU: one RTX 2060 6 GB, one run at a time (~51k steps/s for a human env, 1024 envs). Details per run: rl_optimization_log.md.

| UTC | Run | What | Outcome |
|---|---|---|---|
| 20:22–21:30 | g1 (other session) | from scratch, launch recipe | FAILED: falls at once (episode 3.7 steps) |
| 21:39–21:51 | g2 | + reward floor | FAILED: sits on the floor (toddler 0/10) |
| 21:58–22:26 | g3 | + fall-height termination | toddler 10/10 x3 at 43M, but stomping (20 BW foot force); reward declining |
| 22:26–22:46 | g4 | from g3 @ 43M, contact cost /10, alive 5 | worse: 65–76 BW, stand 2/10 |
| 22:53–23:10 | g5 probe | from g3 @ 43M, full contact cost, no floor, alive 15, action rate −0.1 | stomping gone (0.7–1.8 BW, jerk 0.009) but kneels: toddler 0/10 |
| 23:16–23:55 | g6 | from g5, + knee/elbow/wrist/torso height termination | **stand 10/10** (Matt-level smoothness), pushes 4 / 6 of 10, graduation 0/100 |
| 23:56–00:53 | g7 | from g6, same recipe (PPO losses logged from here) | 48M: stand 10, push walking 10, push standing 6; final regressed (stand 0); graduation 0/100 |
| 00:57–01:10 | g8 | from g7 @ 48M, alive 15 → 3 | collapsed (episode 431 → 79): too big a reward-scale jump for the critic |
| 01:11–01:35 | g9 | from g7 @ 48M, alive 8, learning rate 1e-4 | stable (stand 9, push walking 9–10) but stands still under a walk command (0.02 m/s at 0.8) |
| 01:36–02:24 | g10 | from g9 @ 38M, wide speed-tracking weight ×4, alive 5 | **walks** (0.50 m/s on 0.8 at 57M; walking error 0.49 → 0.21, push walking 10/10) but falls holding still (stand 0/10) |
| 02:25–03:08 | g11 | from g10, stand-still pose cost −2 → −0.5 | **toddler tier passed** at 81M & 97M (10/10 ×3, 1.16 BW, jerk 0.011); graduation 27/100 at 102.7M (`final/grandma_g11_toddler_params.pkl`) |
| 03:09–03:36 | g12 | from g11, gait symmetry weight ×3 (−1.5 → −4.5) | **toddler 10/10 ×3** (1.06 BW, jerk 0.009); **graduation surged 27/100 → 52/100 (37.7M) → 71/100 (71.6M, err 0.232)** (`final/grandma_g12_grad71_params.pkl`) |
| 03:36–04:15 | g13 | from g12 @ 71.6M, same recipe | graduation **84/100** at 24M (child-tier speed error 0.183 < 0.2), then 78 / 75 (plateau) (`final/grandma_g13_grad84_params.pkl`) |
| 04:16–04:40 | g14 | g13 @ 24M fine-tune, learning rate 5e-5 | **GRADUATED: 94/100** (fresh seeds 91/100, 0 NaN); toddler 10/10 ×3; ONNX exported `training/final/grandma_g14.onnx` (not deployed) |
