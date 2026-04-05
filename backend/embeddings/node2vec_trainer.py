# """
# backend/embeddings/node2vec_trainer.py

# Graph Representation Learning using Node2Vec.

# Node2Vec performs biased random walks on the graph to generate
# node sequences, then trains a Skip-Gram (Word2Vec) model to learn
# low-dimensional node embeddings.

# The p and q parameters control the walk strategy:
#   - p (return parameter): probability of returning to previous node
#   - q (in-out parameter): q<1 → DFS-like (captures communities)
#                           q>1 → BFS-like (captures local structure)

# For fraud detection:
#   - Low q values help discover fraud rings (community-like)
#   - Embeddings encode structural role + neighborhood context
# """

# import numpy as np
# import json
# import logging
# from pathlib import Path
# from typing import Dict, List, Optional, Tuple

# import networkx as nx
# from node2vec import Node2Vec
# from gensim.models import Word2Vec

# logger = logging.getLogger(__name__)


# class FraudNode2Vec:
#     """
#     Trains Node2Vec embeddings on the transaction graph.

#     Workflow:
#       1. Convert MultiDiGraph → simple weighted graph
#       2. Run biased random walks
#       3. Train Skip-Gram model on walks
#       4. Extract embedding matrix + node ID mapping
#     """

#     def __init__(
#         self,
#         dimensions: int = 64,
#         walk_length: int = 30,
#         num_walks: int = 200,
#         p: float = 1.0,
#         q: float = 0.5,
#         window: int = 10,
#         workers: int = 4,
#         epochs: int = 5,
#         seed: int = 42,
#     ):
#         self.dimensions = dimensions
#         self.walk_length = walk_length
#         self.num_walks = num_walks
#         self.p = p
#         self.q = q
#         self.window = window
#         self.workers = workers
#         self.epochs = epochs
#         self.seed = seed

#         self.model: Optional[Word2Vec] = None
#         self.node_id_map: Dict[str, int] = {}       # node_name → row index
#         self.id_node_map: Dict[int, str] = {}       # row index → node_name
#         self.embeddings: Optional[np.ndarray] = None

#     # ──────────────────────────────────────────────────────────────────
#     # Graph preparation
#     # ──────────────────────────────────────────────────────────────────

#     def _prepare_graph(self, G: nx.MultiDiGraph) -> nx.Graph:
#         """
#         Convert MultiDiGraph to a simple undirected weighted Graph
#         for Node2Vec random walks.

#         Edge weights = total transaction amount (log-scaled).
#         Self-loops are removed.
#         """
#         simple = nx.Graph()

#         for u, v, data in G.edges(data=True):
#             if u == v:
#                 continue  # skip self-loops
#             w = np.log1p(data.get("weight", 1.0))
#             if simple.has_edge(u, v):
#                 simple[u][v]["weight"] += w
#             else:
#                 simple.add_edge(u, v, weight=w)

#         # Copy node attributes
#         for node, attrs in G.nodes(data=True):
#             if node in simple:
#                 simple.nodes[node].update(attrs)

#         logger.info(
#             f"Prepared graph: {simple.number_of_nodes()} nodes, "
#             f"{simple.number_of_edges()} edges"
#         )
#         return simple

#     # ──────────────────────────────────────────────────────────────────
#     # Training
#     # ──────────────────────────────────────────────────────────────────

#     def train(self, G: nx.MultiDiGraph) -> np.ndarray:
#         """
#         Full Node2Vec training pipeline.

#         Args:
#             G: The transaction heterogeneous graph

#         Returns:
#             embeddings: np.ndarray of shape (N, dimensions)
#         """
#         logger.info("Starting Node2Vec training...")

#         # Step 1: Prepare graph
#         simple_graph = self._prepare_graph(G)

#         if simple_graph.number_of_nodes() < 2:
#             raise ValueError("Graph too small for embedding training.")

#         # Step 2: Initialize Node2Vec and generate walks
#         logger.info(f"Generating {self.num_walks} walks of length {self.walk_length}...")
#         n2v = Node2Vec(
#             simple_graph,
#             dimensions=self.dimensions,
#             walk_length=self.walk_length,
#             num_walks=self.num_walks,
#             p=self.p,
#             q=self.q,
#             workers=self.workers,
#             seed=self.seed,
#             quiet=True,
#         )

#         # Step 3: Train Word2Vec (Skip-Gram) on walks
#         logger.info("Training Skip-Gram model on random walks...")
#         self.model = n2v.fit(
#             window=self.window,
#             min_count=1,
#             batch_words=4,
#             epochs=self.epochs,
#         )

#         # Step 4: Build embedding matrix
#         self._build_embedding_matrix(simple_graph)

#         logger.info(
#             f"Embeddings trained: shape={self.embeddings.shape}"
#         )
#         return self.embeddings

#     def _build_embedding_matrix(self, G: nx.Graph):
#         """
#         Extract embedding vectors and build:
#           - node_id_map: node_name → row index
#           - id_node_map: row index → node_name
#           - embeddings: (N, dim) numpy array
#         """
#         nodes = list(G.nodes())
#         self.node_id_map = {node: i for i, node in enumerate(nodes)}
#         self.id_node_map = {i: node for node, i in self.node_id_map.items()}

#         emb_list = []
#         for node in nodes:
#             node_str = str(node)
#             if node_str in self.model.wv:
#                 emb_list.append(self.model.wv[node_str])
#             else:
#                 # Node not in vocabulary → use zero vector
#                 emb_list.append(np.zeros(self.dimensions))

#         self.embeddings = np.array(emb_list, dtype=np.float32)

#     # ──────────────────────────────────────────────────────────────────
#     # Retrieval helpers
#     # ──────────────────────────────────────────────────────────────────

#     def get_embedding(self, node_name: str) -> Optional[np.ndarray]:
#         """Get embedding vector for a single node."""
#         if self.model is None:
#             raise RuntimeError("Model not trained. Call train() first.")
#         node_str = str(node_name)
#         if node_str in self.model.wv:
#             return self.model.wv[node_str]
#         return None

#     def get_most_similar(
#         self,
#         node_name: str,
#         topn: int = 10
#     ) -> List[Tuple[str, float]]:
#         """
#         Find most similar nodes by embedding cosine similarity.
#         Useful for identifying structurally similar accounts.
#         """
#         if self.model is None:
#             raise RuntimeError("Model not trained.")
#         node_str = str(node_name)
#         if node_str not in self.model.wv:
#             return []
#         return self.model.wv.most_similar(node_str, topn=topn)

#     def get_fraud_neighbor_ratio(
#         self,
#         node_name: str,
#         G: nx.MultiDiGraph,
#         topn: int = 10
#     ) -> float:
#         """
#         Embedding-based fraud neighbor ratio:
#         Among topN most similar nodes in embedding space,
#         what fraction are known fraud accounts?
#         """
#         similar = self.get_most_similar(node_name, topn=topn)
#         if not similar:
#             return 0.0
#         fraud_count = sum(
#             1 for (node, _) in similar
#             if G.nodes.get(node, {}).get("is_fraud", 0) == 1
#         )
#         return fraud_count / len(similar)

#     # ──────────────────────────────────────────────────────────────────
#     # Persistence
#     # ──────────────────────────────────────────────────────────────────

#     def save(self, embeddings_path: str, map_path: str, model_path: str):
#         """Save embeddings, ID mapping, and Word2Vec model."""
#         np.save(embeddings_path, self.embeddings)
#         with open(map_path, "w") as f:
#             json.dump(self.node_id_map, f)
#         self.model.save(model_path)
#         logger.info(f"Embeddings saved to {embeddings_path}")

#     def load(self, embeddings_path: str, map_path: str, model_path: str):
#         """Load saved embeddings and model."""
#         self.embeddings = np.load(embeddings_path)
#         with open(map_path, "r") as f:
#             self.node_id_map = json.load(f)
#         self.id_node_map = {v: k for k, v in self.node_id_map.items()}
#         self.model = Word2Vec.load(model_path)
#         logger.info(f"Embeddings loaded: shape={self.embeddings.shape}")


# class DeepWalkTrainer:
#     """
#     DeepWalk: simplified Node2Vec with p=1, q=1 (uniform random walks).
#     Included as a comparison baseline.
#     """

#     def __init__(self, dimensions: int = 64, walk_length: int = 40,
#                  num_walks: int = 100, window: int = 5, workers: int = 4):
#         self.trainer = FraudNode2Vec(
#             dimensions=dimensions,
#             walk_length=walk_length,
#             num_walks=num_walks,
#             p=1.0,   # uniform → DeepWalk behavior
#             q=1.0,
#             window=window,
#             workers=workers,
#         )

#     def train(self, G: nx.MultiDiGraph) -> np.ndarray:
#         logger.info("Training DeepWalk (uniform random walks)...")
#         return self.trainer.train(G)

#     @property
#     def embeddings(self):
#         return self.trainer.embeddings

#     @property
#     def node_id_map(self):
#         return self.trainer.node_id_map
# """
# backend/embeddings/node2vec_trainer.py

# Graph Representation Learning using Node2Vec.

# Node2Vec performs biased random walks on the graph to generate
# node sequences, then trains a Skip-Gram (Word2Vec) model to learn
# low-dimensional node embeddings.

# The p and q parameters control the walk strategy:
#   - p (return parameter): probability of returning to previous node
#   - q (in-out parameter): q<1 → DFS-like (captures communities)
#                           q>1 → BFS-like (captures local structure)

# For fraud detection:
#   - Low q values help discover fraud rings (community-like)
#   - Embeddings encode structural role + neighborhood context
# """

# import numpy as np
# import json
# import logging
# from pathlib import Path
# from typing import Dict, List, Optional, Tuple

# import networkx as nx
# from node2vec import Node2Vec
# from gensim.models import Word2Vec

# logger = logging.getLogger(__name__)


# class FraudNode2Vec:
#     """
#     Trains Node2Vec embeddings on the transaction graph.

#     Workflow:
#       1. Convert MultiDiGraph → simple weighted graph
#       2. Run biased random walks
#       3. Train Skip-Gram model on walks
#       4. Extract embedding matrix + node ID mapping
#     """

#     def __init__(
#         self,
#         dimensions: int = 64,
#         walk_length: int = 30,
#         num_walks: int = 200,
#         p: float = 1.0,
#         q: float = 0.5,
#         window: int = 10,
#         workers: int = 4,
#         epochs: int = 5,
#         seed: int = 42,
#     ):
#         self.dimensions = dimensions
#         self.walk_length = walk_length
#         self.num_walks = num_walks
#         self.p = p
#         self.q = q
#         self.window = window
#         self.workers = workers
#         self.epochs = epochs
#         self.seed = seed

#         self.model: Optional[Word2Vec] = None
#         self.node_id_map: Dict[str, int] = {}       # node_name → row index
#         self.id_node_map: Dict[int, str] = {}       # row index → node_name
#         self.embeddings: Optional[np.ndarray] = None

#     # ──────────────────────────────────────────────────────────────────
#     # Graph preparation
#     # ──────────────────────────────────────────────────────────────────

#     def _prepare_graph(self, G: nx.MultiDiGraph) -> nx.Graph:
#         """
#         Convert MultiDiGraph to a simple undirected weighted Graph
#         for Node2Vec random walks.

#         Edge weights = total transaction amount (log-scaled).
#         Self-loops are removed.
#         """
#         simple = nx.Graph()

#         for u, v, data in G.edges(data=True):
#             if u == v:
#                 continue  # skip self-loops
#             w = np.log1p(data.get("weight", 1.0))
#             if simple.has_edge(u, v):
#                 simple[u][v]["weight"] += w
#             else:
#                 simple.add_edge(u, v, weight=w)

#         # Copy node attributes
#         for node, attrs in G.nodes(data=True):
#             if node in simple:
#                 simple.nodes[node].update(attrs)

#         logger.info(
#             f"Prepared graph: {simple.number_of_nodes()} nodes, "
#             f"{simple.number_of_edges()} edges"
#         )
#         return simple

#     # ──────────────────────────────────────────────────────────────────
#     # Training
#     # ──────────────────────────────────────────────────────────────────

#     def train(self, G: nx.MultiDiGraph) -> np.ndarray:
#         """
#         Full Node2Vec training pipeline.

#         Args:
#             G: The transaction heterogeneous graph

#         Returns:
#             embeddings: np.ndarray of shape (N, dimensions)
#         """
#         logger.info("Starting Node2Vec training...")

#         # Step 1: Prepare graph
#         simple_graph = self._prepare_graph(G)

#         if simple_graph.number_of_nodes() < 2:
#             raise ValueError("Graph too small for embedding training.")

#         # Step 2: Initialize Node2Vec and generate walks
#         logger.info(f"Generating {self.num_walks} walks of length {self.walk_length}...")
#         n2v = Node2Vec(
#             simple_graph,
#             dimensions=self.dimensions,
#             walk_length=self.walk_length,
#             num_walks=self.num_walks,
#             p=self.p,
#             q=self.q,
#             workers=self.workers,
#             seed=self.seed,
#             quiet=True,
#         )

#         # Step 3: Train Word2Vec (Skip-Gram) on walks
#         logger.info("Training Skip-Gram model on random walks...")
#         self.model = n2v.fit(
#             window=self.window,
#             min_count=1,
#             batch_words=4,
#             epochs=self.epochs,
#         )

#         # Step 4: Build embedding matrix
#         self._build_embedding_matrix(simple_graph)

#         logger.info(
#             f"Embeddings trained: shape={self.embeddings.shape}"
#         )
#         return self.embeddings

#     def _build_embedding_matrix(self, G: nx.Graph):
#         """
#         Extract embedding vectors and build:
#           - node_id_map: node_name → row index
#           - id_node_map: row index → node_name
#           - embeddings: (N, dim) numpy array
#         """
#         nodes = list(G.nodes())
#         self.node_id_map = {node: i for i, node in enumerate(nodes)}
#         self.id_node_map = {i: node for node, i in self.node_id_map.items()}

#         emb_list = []
#         for node in nodes:
#             node_str = str(node)
#             if node_str in self.model.wv:
#                 emb_list.append(self.model.wv[node_str])
#             else:
#                 # Node not in vocabulary → use zero vector
#                 emb_list.append(np.zeros(self.dimensions))

#         self.embeddings = np.array(emb_list, dtype=np.float32)

#     # ──────────────────────────────────────────────────────────────────
#     # Retrieval helpers
#     # ──────────────────────────────────────────────────────────────────

#     def get_embedding(self, node_name: str) -> Optional[np.ndarray]:
#         """Get embedding vector for a single node."""
#         if self.model is None:
#             raise RuntimeError("Model not trained. Call train() first.")
#         node_str = str(node_name)
#         if node_str in self.model.wv:
#             return self.model.wv[node_str]
#         return None

#     def get_most_similar(
#         self,
#         node_name: str,
#         topn: int = 10
#     ) -> List[Tuple[str, float]]:
#         """
#         Find most similar nodes by embedding cosine similarity.
#         Useful for identifying structurally similar accounts.
#         """
#         if self.model is None:
#             raise RuntimeError("Model not trained.")
#         node_str = str(node_name)
#         if node_str not in self.model.wv:
#             return []
#         return self.model.wv.most_similar(node_str, topn=topn)

#     def get_fraud_neighbor_ratio(
#         self,
#         node_name: str,
#         G: nx.MultiDiGraph,
#         topn: int = 10
#     ) -> float:
#         """
#         Embedding-based fraud neighbor ratio:
#         Among topN most similar nodes in embedding space,
#         what fraction are known fraud accounts?
#         """
#         similar = self.get_most_similar(node_name, topn=topn)
#         if not similar:
#             return 0.0
#         fraud_count = sum(
#             1 for (node, _) in similar
#             if G.nodes.get(node, {}).get("is_fraud", 0) == 1
#         )
#         return fraud_count / len(similar)

#     # ──────────────────────────────────────────────────────────────────
#     # Persistence
#     # ──────────────────────────────────────────────────────────────────

#     def save(self, embeddings_path: str, map_path: str, model_path: str):
#         """Save embeddings, ID mapping, and Word2Vec model."""
#         np.save(embeddings_path, self.embeddings)
#         with open(map_path, "w") as f:
#             json.dump(self.node_id_map, f)
#         self.model.save(model_path)
#         logger.info(f"Embeddings saved to {embeddings_path}")

#     def load(self, embeddings_path: str, map_path: str, model_path: str):
#         """Load saved embeddings and model."""
#         self.embeddings = np.load(embeddings_path)
#         with open(map_path, "r") as f:
#             self.node_id_map = json.load(f)
#         self.id_node_map = {v: k for k, v in self.node_id_map.items()}
#         self.model = Word2Vec.load(model_path)
#         logger.info(f"Embeddings loaded: shape={self.embeddings.shape}")


# class DeepWalkTrainer:
#     """
#     DeepWalk: simplified Node2Vec with p=1, q=1 (uniform random walks).
#     Included as a comparison baseline.
#     """

#     def __init__(self, dimensions: int = 64, walk_length: int = 40,
#                  num_walks: int = 100, window: int = 5, workers: int = 4):
#         self.trainer = FraudNode2Vec(
#             dimensions=dimensions,
#             walk_length=walk_length,
#             num_walks=num_walks,
#             p=1.0,   # uniform → DeepWalk behavior
#             q=1.0,
#             window=window,
#             workers=workers,
#         )

#     def train(self, G: nx.MultiDiGraph) -> np.ndarray:
#         logger.info("Training DeepWalk (uniform random walks)...")
#         return self.trainer.train(G)

#     @property
#     def embeddings(self):
#         return self.trainer.embeddings

#     @property
#     def node_id_map(self):
#         return self.trainer.node_id_map
"""
backend/embeddings/node2vec_trainer.py

Graph Representation Learning using Node2Vec.

FIX LOG:
  [BUG-8]  Removed batch_words=4 from n2v.fit() — removed in Gensim 4.0.
           Gensim 4.x uses epochs= parameter directly on fit().
  [BUG-9]  Added platform guard for workers on Windows (multiprocessing issues).
"""

import numpy as np
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx
from node2vec import Node2Vec
from gensim.models import Word2Vec

logger = logging.getLogger(__name__)


class FraudNode2Vec:
    """
    Trains Node2Vec embeddings on the transaction graph.

    Workflow:
      1. Convert MultiDiGraph → simple weighted graph
      2. Run biased random walks
      3. Train Skip-Gram model on walks
      4. Extract embedding matrix + node ID mapping
    """

    def __init__(
        self,
        dimensions: int = 64,
        walk_length: int = 30,
        num_walks: int = 200,
        p: float = 1.0,
        q: float = 0.5,
        window: int = 10,
        workers: int = 4,
        epochs: int = 5,
        seed: int = 42,
    ):
        self.dimensions = dimensions
        self.walk_length = walk_length
        self.num_walks = num_walks
        self.p = p
        self.q = q
        self.window = window
        # [BUG-9] Windows multiprocessing guard
        self.workers = 1 if sys.platform == "win32" else workers
        self.epochs = epochs
        self.seed = seed

        self.model: Optional[Word2Vec] = None
        self.node_id_map: Dict[str, int] = {}
        self.id_node_map: Dict[int, str] = {}
        self.embeddings: Optional[np.ndarray] = None

    def _prepare_graph(self, G: nx.MultiDiGraph) -> nx.Graph:
        """
        Convert MultiDiGraph to a simple undirected weighted Graph
        for Node2Vec random walks.
        Edge weights = total transaction amount (log-scaled).
        Self-loops removed.
        """
        simple = nx.Graph()
        for u, v, data in G.edges(data=True):
            if u == v:
                continue
            w = np.log1p(data.get("weight", 1.0))
            if simple.has_edge(u, v):
                simple[u][v]["weight"] += w
            else:
                simple.add_edge(u, v, weight=w)
        for node, attrs in G.nodes(data=True):
            if node in simple:
                simple.nodes[node].update(attrs)
        logger.info(
            f"Prepared graph: {simple.number_of_nodes()} nodes, "
            f"{simple.number_of_edges()} edges"
        )
        return simple

    def train(self, G: nx.MultiDiGraph) -> np.ndarray:
        """
        Full Node2Vec training pipeline.

        Args:
            G: The transaction heterogeneous graph

        Returns:
            embeddings: np.ndarray of shape (N, dimensions)
        """
        logger.info("Starting Node2Vec training...")
        simple_graph = self._prepare_graph(G)

        if simple_graph.number_of_nodes() < 2:
            raise ValueError("Graph too small for embedding training.")

        logger.info(
            f"Generating {self.num_walks} walks of length {self.walk_length} "
            f"(p={self.p}, q={self.q})..."
        )
        n2v = Node2Vec(
            simple_graph,
            dimensions=self.dimensions,
            walk_length=self.walk_length,
            num_walks=self.num_walks,
            p=self.p,
            q=self.q,
            workers=self.workers,
            seed=self.seed,
            quiet=True,
        )

        # [BUG-8] FIXED: removed batch_words=4 (removed in Gensim 4.0)
        # epochs= is passed directly; Gensim 4.x handles it correctly.
        logger.info("Training Skip-Gram model on random walks...")
        self.model = n2v.fit(
            window=self.window,
            min_count=1,
            epochs=self.epochs,
        )

        self._build_embedding_matrix(simple_graph)
        logger.info(f"Embeddings trained: shape={self.embeddings.shape}")

        # Save checkpoint immediately after training completes.
        # If anything crashes in Steps 4-6 downstream, you can re-run
        # with --skip-embeddings and skip this entire painful step.
        try:
            from configs.settings import EXPERIMENTS_DIR
            checkpoint_path = str(EXPERIMENTS_DIR / "node2vec_checkpoint.model")
            self.model.save(checkpoint_path)
            logger.info(f"Checkpoint saved → {checkpoint_path}")
        except Exception as e:
            logger.warning(f"Checkpoint save failed (non-fatal): {e}")

        return self.embeddings

    def _build_embedding_matrix(self, G: nx.Graph):
        """
        Extract embedding vectors and build index maps.
        Node order is deterministic: sorted list of graph nodes.
        """
        # Sort for deterministic ordering — prevents silent index mismatch
        nodes = sorted(G.nodes())
        self.node_id_map = {node: i for i, node in enumerate(nodes)}
        self.id_node_map = {i: node for node, i in self.node_id_map.items()}

        emb_list = []
        missing = 0
        for node in nodes:
            node_str = str(node)
            if node_str in self.model.wv:
                emb_list.append(self.model.wv[node_str])
            else:
                emb_list.append(np.zeros(self.dimensions))
                missing += 1

        if missing > 0:
            logger.warning(
                f"{missing} nodes had no embedding (zero-vector fallback). "
                "These nodes were isolated in the walk graph."
            )

        self.embeddings = np.array(emb_list, dtype=np.float32)

    def get_embedding(self, node_name: str) -> Optional[np.ndarray]:
        """Get embedding vector for a single node."""
        if self.model is None:
            raise RuntimeError("Model not trained. Call train() first.")
        node_str = str(node_name)
        if node_str in self.model.wv:
            return self.model.wv[node_str]
        return None

    def get_most_similar(
        self,
        node_name: str,
        topn: int = 10
    ) -> List[Tuple[str, float]]:
        """Find most similar nodes by embedding cosine similarity."""
        if self.model is None:
            raise RuntimeError("Model not trained.")
        node_str = str(node_name)
        if node_str not in self.model.wv:
            return []
        return self.model.wv.most_similar(node_str, topn=topn)

    def get_fraud_neighbor_ratio(
        self,
        node_name: str,
        G: nx.MultiDiGraph,
        topn: int = 10
    ) -> float:
        """Fraction of topN embedding-similar nodes that are known fraudsters."""
        similar = self.get_most_similar(node_name, topn=topn)
        if not similar:
            return 0.0
        fraud_count = sum(
            1 for (node, _) in similar
            if G.nodes.get(node, {}).get("is_fraud", 0) == 1
        )
        return fraud_count / len(similar)

    def save(self, embeddings_path: str, map_path: str, model_path: str):
        """Save embeddings, ID mapping, and Word2Vec model."""
        np.save(embeddings_path, self.embeddings)
        with open(map_path, "w") as f:
            json.dump(self.node_id_map, f)
        self.model.save(model_path)
        logger.info(f"Embeddings saved to {embeddings_path}")

    def load(self, embeddings_path: str, map_path: str, model_path: str):
        """Load saved embeddings and model."""
        self.embeddings = np.load(embeddings_path)
        with open(map_path, "r") as f:
            self.node_id_map = json.load(f)
        self.id_node_map = {v: k for k, v in self.node_id_map.items()}
        self.model = Word2Vec.load(model_path)
        logger.info(f"Embeddings loaded: shape={self.embeddings.shape}")


class DeepWalkTrainer:
    """
    DeepWalk: simplified Node2Vec with p=1, q=1 (uniform random walks).
    Baseline comparison model.
    """

    def __init__(self, dimensions: int = 64, walk_length: int = 40,
                 num_walks: int = 100, window: int = 5, workers: int = 4):
        self.trainer = FraudNode2Vec(
            dimensions=dimensions,
            walk_length=walk_length,
            num_walks=num_walks,
            p=1.0,
            q=1.0,
            window=window,
            workers=workers,
        )

    def train(self, G: nx.MultiDiGraph) -> np.ndarray:
        logger.info("Training DeepWalk (uniform random walks)...")
        return self.trainer.train(G)

    @property
    def embeddings(self):
        return self.trainer.embeddings

    @property
    def node_id_map(self):
        return self.trainer.node_id_map