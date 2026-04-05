FIX LOG:
  [BUG-1]  REMOVED double normalization. The ensemble sum of two already-
           normalized scores [0,1] already lives in [0,1]. The final
           _normalize_scores() call was collapsing the distribution and making
           the 0.65 threshold meaningless (top score was always 1.0 by construction).
           Now the ensemble is clipped to [0,1] — preserving true signal magnitude.

  [BUG-4]  evaluate_against_labels now filters to TRANSACTION nodes only.
           Account nodes with is_fraud=1 are contaminated (dest accounts get
           tagged fraud just for receiving from a fraudster in _upsert_account_node).
           Only transaction nodes have unambiguous isFraud ground-truth labels.
  [BUG-13] fraud_clusters.json now written to DATA_DIR (absolute, from settings.py)
           not "data/fraud_clusters.json" (relative to CWD).

  [BUG-14] ANOMALY_CONFIG nested sub-dicts now correctly unpacked when
           constructing FraudAnomalyDetector. Settings.py is the single
           source of truth for all hyperparameters.

  [BUG-5]  true_labels now built from TRANSACTION nodes only (tx_* prefix).
           Account nodes are contaminated — destination accounts receive
           is_fraud=1 just for receiving from a fraudster. Transaction nodes
           have unambiguous isFraud ground-truth from the original PaySim row.

  [BUG-12] detection_metrics.json written to DATA_DIR so main.py
           /api/analytics/metrics endpoint can serve it. A new endpoint
           must be added to main.py (see inline note).

  [BUG-2]  Embedding → node_name alignment: node_id_map now loaded and
           iterated in sorted() order to match the sorted() order used
           in FraudNode2Vec._build_embedding_matrix. Prevents silent
           embedding/score misalignment.

  [BUG-3]  LOF fit_predict() return value was discarded; call is now lof.fit()
           then access negative_outlier_factor_ directly, which is cleaner
           and avoids the redundant pass.

  [BUG-5]  FIXED fraud label propagation. Previously, destination account
           nodes were tagged is_fraud=1 if the transaction's isFraud=1.
           In PaySim, isFraud labels the ORIGINATOR, not the destination.
           Destination accounts now receive is_fraud_dest=1 (mule flag)
           to distinguish from is_fraud (initiator of fraud).
           This prevents true_label contamination in evaluate_against_labels.

  [BUG-6]  FIXED: node_type not updated on re-encounter.
           If a node appears first as an account then as a merchant,
           we now upgrade the type to merchant (more specific wins).

  [BUG-7]  FIXED: account→account edge accumulation bug.
           G.has_edge(orig_id, dest_id) returns True for ANY edge between
           the pair (including tx-intermediate edges). We now use a dedicated
           lookup via edge key tracking to safely find/create transfers_to edges.

  [BUG-8]  Removed batch_words=4 from n2v.fit() — removed in Gensim 4.0.
           Gensim 4.x uses epochs= parameter directly on fit().
 
  [BUG-9]  Added platform guard for workers on Windows (multiprocessing issues).

  [BUG-10] FIXED: risk_label thresholds aligned with ANOMALY_CONFIG.
           Was: CRITICAL ≥ 0.7, HIGH ≥ 0.5, MEDIUM otherwise.
           Now: CRITICAL = 1.0 (all nodes fraud), HIGH ≥ 0.7, MEDIUM ≥ 0.4.
           This matches the fraud_ratio_threshold=0.4 and is academically defensible.

  [BUG-11] FIXED: Louvain version guard. best_partition() kwarg changed between
           versions. Now attempts randomize=False first, falls back to
           random_state=42 for newer versions.
