# Task Family Taxonomy

This document provides an overview of all task families in the taxonomy.

## Summary

- **Total Families**: 17
- **Total Paradigms**: 410

## Task Families

### Selective & Spatial Attention (`tf_attention_selective`)


Paradigms probing orienting, selection, and sustained/temporal attention via cue–target structures, visual search streams, vigilance demands, and dynamic selection (tracking). Covers spatial/feature/object-based attention, temporal attention in RSVP (rapid serial visual presentation), sustained attention/vigilance (CPT/Continuous Performance Test family), and selection under movement.

- **Subfamilies**: 7
- **Paradigms**: 30

---

### Conflict & Inhibitory Control (`tf_conflict_inhibition`)


Response selection under conflict and outright response inhibition. Includes stimulus–stimulus conflict (S–S, e.g., Stroop), stimulus–response/spatial compatibility (S–R, Simon), response–response competition (Flanker), and inhibitory control paradigms that require withholding or cancelling an action (Go/No-go, Go NoGo, Stop-signal, Stop Signal), plus canonical "adaptation" designs (negative priming, proportion congruent, sequential congruency, conflict adaptation, Gratton effect).

- **Subfamilies**: 5
- **Paradigms**: 20

---

### Perceptual Detection & Discrimination (`tf_detection_discrimination`)


Psychophysical paradigms measuring detectability, sensitivity (d′), thresholds/JNDs, precision, and bias (PSE) across space, time, motion, and form. Includes classic signal-detection (Yes/No, mAFC), discrimination and estimation (contrast/orientation/spatial frequency/color/motion), temporal order/simultaneity and flicker fusion, masking/crowding/adaptation, and (optionally) multistability/illusion tasks when analyzed as discrimination/bias.

- **Subfamilies**: 6
- **Paradigms**: 20
- **Examples**: `yes_no_detection`, `2afc`, `orientation_discrimination`, `contrast_sensitivity`, `motion_coherence`, ... (+5 more)

---

### Interoception & Physiological Challenge (`tf_interoception_challenge`)


Tasks probing interoceptive accuracy/awareness (cardiorespiratory/gastric) and responses to controlled physiological perturbations (CO₂ hypercapnia, respiratory load, cold pressor, thermal pain, orthostatic/LBNP, drug challenge, breath-hold). Includes metacognitive assessments (confidence/meta-d′), continuous tracking, and standardized physiological acquisition (ECG/PPG, respiration, SpO₂, EtCO₂, SCR, BP). Use medical screening and safety oversight for challenge paradigms.

- **Subfamilies**: 2
- **Paradigms**: 18
- **Examples**: `heartbeat_counting`, `heartbeat_discrimination_synchrony`, `heartbeat_tracking`, `respiratory_load_detection`, `hypercapnia_co2`, ... (+7 more)

---

### Language (Semantic/Comprehension/Production) (`tf_language_semantic`)


Language tasks spanning lexical access/orthography, semantic/conceptual processing, phonology/morphology, sentence-level syntax and integration, discourse/narrative comprehension & pragmatics/prosody, and production (naming/generation/fluency). Aligns subfamilies to ONVOC language nodes for clean crosswalks and downstream use.

- **Subfamilies**: 8
- **Paradigms**: 31
- **Examples**: `lexical_decision`, `semantic_decision`, `sentence_comprehension`, `story_listening`, `picture_naming`, ... (+3 more)

---

### Functional Localizers & Baseline Tasks (`tf_localizers_baseline`)

**Meta Family**: This is a meta family for special handling.

Canonical localizers and baseline paradigms used to define regions-of-interest (ROI) or establish control conditions. Marked as `meta: true` for special handling: exclude from construct scoring, prioritize for ROI extraction and QC. Includes sensory maps (retinotopy/tonotopy/somatotopy), visual category localizers (FFA/PPA/LOC/EBA/VWFA/MT+), language and ToM localizers, plus resting/passive baselines. Each paradigm lists recommended contrasts and target ROIs.

- **Subfamilies**: 8
- **Paradigms**: 28
- **Examples**: `retinotopy`, `prf_mapping`, `tonotopy`, `voice_localizer`, `motor_localizer`, ... (+13 more)

---

### Episodic & Declarative Memory (`tf_ltm_declarative`)


Encoding and retrieval in long-term memory across recall, recognition, associative/source/context memory, prospective memory, metamemory, and canonical encoding manipulations (levels-of-processing, generation, spacing, testing effect, enactment, imagery, consolidation/sleep). Includes false memory and interference paradigms (DRM, misinformation, retrieval-induced forgetting, directed forgetting).

- **Subfamilies**: 10
- **Paradigms**: 42

---

### Motor Action & Imagery (`tf_motor_action`)


Execution, control, learning, and mental simulation of actions across effectors (eye/hand/fingers/arm). Covers rhythmic/sequenced actions, continuous tracking/trajectory control, oculomotor control (pro/anti/pursuit, adaptation), sensorimotor adaptation (visuomotor rotation/force-field), speed–accuracy trade-offs (Fitts’ law), and motor imagery (visual/kinesthetic) with mental chronometry.

- **Subfamilies**: 6
- **Paradigms**: 20
- **Examples**: `finger_tapping`, `sequential_tapping`, `joystick_tracking`, `pursuit_tracking`, `pro_saccade`, ... (+7 more)

---

### Neurofeedback (Protocol) (`tf_neurofeedback`)

**Meta Family**: This is a meta family for special handling.

Protocol-oriented paradigms where participants regulate neural signals via real-time feedback. Variants include ROI-based rt-fMRI, MVPA/decoder-based, connectivity/network-based, EEG/MEG band-power feedback, and fNIRS hemodynamic feedback. This family is marked `meta: true` for downstream handling (separate from construct scoring): prioritize calibration, latency/QC reporting, transfer tests, and control/sham designs.

- **Subfamilies**: 8
- **Paradigms**: 25
- **Examples**: `rtfmri_roi_regulation`, `decoder_based_nf`, `connectivity_nf`, `eeg_alpha_nf`, `fnirs_pfc_nf`, ... (+2 more)

---

### Affective & Preference Tasks (`tf_preference_affective`)


Tasks assessing affective valuation, liking/preference formation, aesthetic judgment, and mood induction. Includes explicit ratings (valence/arousal/liking/beauty), pairwise preference/choice and willingness-to-pay, aesthetic judgments in visual/music/face domains, attentional/approach biases, and affect/mood induction.

- **Subfamilies**: 7
- **Paradigms**: 23
- **Examples**: `emotion_induction`, `like_dislike_rating`, `aesthetic_preference`, `pairwise_preference`, `bdm_willingness_to_pay`, ... (+2 more)

---

### Category & Probabilistic Learning (`tf_rule_category_learning`)


Learning to assign stimuli to categories based on rules, multi-cue integration, or probabilistic cue–outcome structure. Includes explicit rule discovery vs instructed rules, information-integration (II) with pre-decisional feature combination, prototype/exemplar representation, base-rate/payoff criterion setting, delayed/partial feedback, and generalization/transfer tests across modalities (visual, auditory/phonetic).

- **Subfamilies**: 6
- **Paradigms**: 30

---

### Social Cognition & Interaction (`tf_social_cognition`)


Inferring others’ beliefs, intentions, emotions, and traits; evaluating fairness and cooperation in interactive games; perceiving socially relevant cues (faces, gaze, biological motion); empathy and vicarious valuation; social learning, influence, and norm enforcement. Emphasizes mechanistic readouts (e.g., inequity aversion, reciprocity, ToM accuracy) alongside behavioral DVs.

- **Subfamilies**: 8
- **Paradigms**: 29

---

### Spatial Navigation (`tf_spatial_navigation`)


Navigation and spatial memory in virtual/realistic environments: place learning in mazes, route learning/wayfinding, path integration (dead reckoning), landmark learning and reorientation, and spatial orientation/pointing. Covers allocentric (map-based) vs egocentric (route-based) strategies, boundary geometry vs landmark cues, and cue-conflict manipulations. Readouts include efficiency/optimality (path length/time), heading/pointing error, and probe-based memory indices.

- **Subfamilies**: 6
- **Paradigms**: 19
- **Examples**: `virtual_maze_navigation`, `virtual_morris_water_maze`, `radial_arm_maze`, `route_learning`, `wayfinding`, ... (+3 more)

---

### Task Switching & Cognitive Flexibility (`tf_task_switching`)


Switching task sets or classification rules across trials/blocks. Covers explicitly cued vs predictable run-based switching, voluntary/memory-based switching, three-task sequences that reveal task-set inhibition (N−2), bivalent-stimulus rule congruency effects, and neuropsychological set-shifting (WCST/Wisconsin Card Sorting Test, DCCS/Dimensional Change Card Sort, ID/ED/Intra-Extra Dimensional, TMT-B/Trail Making Test Part B).

- **Subfamilies**: 5
- **Paradigms**: 15

---

### Temporal Order & Interval Timing (`tf_timing_order`)


Time perception and production: temporal order/simultaneity, interval discrimination/estimation/production, bisection/reproduction, synchronization–continuation tapping, foreperiod/hazard preparation, time-to-contact. Emphasizes scalar timing/bayesian accounts, oscillator/entrainment models, and timed-evidence variants.

- **Subfamilies**: 4
- **Paradigms**: 14
- **Examples**: `temporal_order_judgment`, `simultaneity_judgment`, `temporal_bisection`, `interval_reproduction`, `synchronization_continuation`, ... (+2 more)

---

### Value-Based Decision & Learning (`tf_value_based_decision`)


Reward-guided decision paradigms spanning reinforcement learning (bandits, reversals, model-based vs model-free, Pavlovian–instrumental interactions, habit sensitivity) and economic valuation (risk/ambiguity, intertemporal choice, effort-based cost–benefit). Emphasizes model-based readouts (parameterized utility/discount/learning models) in addition to behavioral DVs.

- **Subfamilies**: 8
- **Paradigms**: 22
- **Examples**: `two_armed_bandit`, `probabilistic_reversal`, `two_step_task`, `prospect_theory_choice`, `delay_discounting`, ... (+3 more)

---

### Working Memory (`tf_working_memory`)


Maintenance and updating of information over short delays. Includes short-delay recognition/recall, capacity/precision measures in visual working memory (VWM), continuous-report estimation, online updating in streams, interference/binding/retro-cue effects, spatial/oculomotor WM (working memory), complex span, and multimodal (auditory/verbal/tactile) WM.

- **Subfamilies**: 8
- **Paradigms**: 24

---
