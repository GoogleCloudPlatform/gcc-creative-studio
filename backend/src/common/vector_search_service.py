# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from typing import Any, Dict, List, Optional

from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine import matching_engine_index_endpoint, matching_engine_index
from google.cloud.aiplatform_v1 import IndexDatapoint
import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel, Image as VertexImage, Video as VertexVideo
from vertexai.language_models import TextEmbeddingModel
from src.config.config_service import config_service

logger = logging.getLogger(__name__)

class VectorSearchService:
    """
    Service for interacting with Vertex AI Vector Search.
    Handles upserting and deleting vectors from the index.
    """

    def __init__(self):
        self.cfg = config_service
        self.project_id = self.cfg.PROJECT_ID
        self.location = "us-central1"
        
        aiplatform.init(project=self.project_id, location=self.location)

    def _get_index_endpoint(self) -> matching_engine_index_endpoint.MatchingEngineIndexEndpoint:
        """Retrieves the Index Endpoint object."""
        return matching_engine_index_endpoint.MatchingEngineIndexEndpoint(
            # index_endpoint_name=self.cfg.VECTOR_SEARCH_INDEX_ENDPOINT_ID
            index_endpoint_name="projects/orca-479911/locations/us-central1/indexEndpoints/4526410095600336896" 
        )

    def _get_deployed_index_id(self, index_type: str) -> str:
        """Resolves the deployed index ID based on type ('text' or 'image')."""
        if index_type == "text":
            # return self.cfg.VECTOR_SEARCH_DEPLOYED_TEXT_INDEX_ID
            return "creative_studio_deployed_index_text"
        elif index_type == "image":
            # return self.cfg.VECTOR_SEARCH_DEPLOYED_IMAGE_INDEX_ID
            return "creative_studio_deployed_index_image"
        else:
            raise ValueError(f"Invalid index_type: {index_type}. Must be 'text' or 'image'.")

    def _get_index(self, deployed_index_id: str) -> matching_engine_index.MatchingEngineIndex:
        """Retrieves the MatchingEngineIndex object corresponding to the deployed index ID."""
        endpoint = self._get_index_endpoint()
        index_resource_name = None
        for d in endpoint.deployed_indexes:
            if d.id == deployed_index_id:
                index_resource_name = d.index
                break
        
        if not index_resource_name:
            raise ValueError(f"Deployed index {deployed_index_id} not found in endpoint {endpoint.resource_name}")
            
        return matching_engine_index.MatchingEngineIndex(index_name=index_resource_name)

    def upsert_vectors(self, vectors: List[Dict[str, Any]], index_type: str):
        """
        Upserts vectors to the specified index.
        
        Args:
            vectors: List of dictionaries containing 'id', 'embedding', and optional 'restricts'.
            index_type: 'text' or 'image'
        """
        if not vectors:
            return

        deployed_index_id = self._get_deployed_index_id(index_type)
        index_obj = self._get_index(deployed_index_id)
        
        # Convert dictionaries to IndexDatapoint objects
        datapoints = []
        for v in vectors:
            restricts = []
            if "restricts" in v:
                for r in v["restricts"]:
                    restricts.append({
                        "namespace": r["namespace"],
                        "allow_list": r.get("allow_list", []),
                        "deny_list": r.get("deny_list", [])
                    })
            
            datapoint = IndexDatapoint(
                datapoint_id=v["id"],
                feature_vector=v["embedding"],
                restricts=restricts if restricts else None
            )
            datapoints.append(datapoint)

        logger.info(f"Upserting {len(datapoints)} vectors to index '{deployed_index_id}'")
        try:
            index_obj.upsert_datapoints(
                datapoints=datapoints
            )
            logger.info("Upsert successful.")
        except Exception as e:
            logger.error(f"Failed to upsert vectors: {e}")
            raise

    def delete_vectors(self, ids: List[str], index_type: str):
        """
        Deletes vectors from the specified index.
        
        Args:
            ids: List of vector IDs to delete.
            index_type: 'text' or 'image'
        """
        if not ids:
            return

        deployed_index_id = self._get_deployed_index_id(index_type)
        index_obj = self._get_index(deployed_index_id)

        logger.info(f"Deleting {len(ids)} vectors from index '{deployed_index_id}'")
        try:
            index_obj.remove_datapoints(
                datapoint_ids=ids
            )
            logger.info("Deletion successful.")
        except Exception as e:
            logger.error(f"Failed to delete vectors: {e}")
            raise

    def find_neighbors(
        self, 
        query_embedding: List[float], 
        index_type: str, 
        num_neighbors: int = 5,
        restricts: Optional[List[Dict[str, Any]]] = None,
        sparse_embedding: Optional[Dict[str, float]] = None,
        rrf_ranking_alpha: float = 0.5
    ) -> List[Any]:
        """
        Searches for nearest neighbors using Dense or Hybrid Search.
        
        Args:
            query_embedding: The dense query vector.
            index_type: 'text' or 'image'
            num_neighbors: Number of neighbors to return.
            restricts: List of restrictions (namespaces).
            sparse_embedding: Optional sparse embedding components for Hybrid Search.
            rrf_ranking_alpha: Weighting for RRF (0.0 to 1.0) if using Hybrid Search.
        
        Returns:
            List of search results (MatchNeighbor objects).
        """
        deployed_index_id = self._get_deployed_index_id(index_type)
        index_endpoint = self._get_index_endpoint()
        
        filter_restricts = []
        if restricts:
            for r in restricts:
                filter_restricts.append(
                    matching_engine_index_endpoint.Namespace(
                        name=r["namespace"],
                        allow_tokens=r.get("allow_list", []),
                        deny_tokens=r.get("deny_list", [])
                    )
                )

        # Hybrid Query Support
        if sparse_embedding:
            try:
                from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import HybridQuery
            except ImportError:
                logger.error("HybridQuery not available in installed google-cloud-aiplatform version.")
                raise

            # Expecting sparse_embedding to be {'values': [...], 'dimensions': [...]}
            # validation
            if not isinstance(sparse_embedding, dict) or 'values' not in sparse_embedding or 'dimensions' not in sparse_embedding:
                logger.warning("Invalid sparse_embedding format. Expected {'values': list, 'dimensions': list}. Falling back to dense.")
                # We can either fallback or raise. The user provided explicit code, so let's try to be robust.
                # If invalid, actually fallback to dense is safer for runtime stability unless strictness is required.
                queries = [query_embedding]
            else:
                hybrid_query = HybridQuery(
                    dense_embedding=query_embedding,
                    sparse_embedding_dimensions=sparse_embedding['dimensions'],
                    sparse_embedding_values=sparse_embedding['values'],
                    rrf_ranking_alpha=rrf_ranking_alpha
                )
                queries = [hybrid_query]
        else:
            queries = [query_embedding]

        try:
            response = index_endpoint.find_neighbors(
                deployed_index_id=deployed_index_id,
                queries=queries,
                num_neighbors=num_neighbors,
                filter=filter_restricts if filter_restricts else None
            )
            # Response is list of lists (one per query). We only have one query.
            if response:
               return response[0]
            return []
        except Exception as e:
            logger.error(f"Failed to search vectors: {e}")
            return []

    def generate_embedding(
        self, 
        content: Any, 
        model_type: Optional[str] = None
    ) -> Optional[List[float]]:
        """
        Generates an embedding for the given text or multimodal content.
        
        Args:
            content: A string (for text embedding) or a list of parts (for multimodal).
            model_type: Optional "text" or "multimodal" to force model selection.
            
        Returns:
            A list of floats representing the embedding, or None if failed.
        """

        # Determine model
        model_name = "text-embedding-005"
        if isinstance(content, list) or model_type == "multimodal":
             model_name = "multimodal-embedding-001"
             
        try:
            
            if model_name == "multimodal-embedding-001":
                mm_model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
                
                image = None
                video = None
                text = None
                
                if isinstance(content, list):
                    for part in content:
                        if hasattr(part, "text") and part.text:
                            text = part.text
                        elif hasattr(part, "file_data") and part.file_data:
                             if part.file_data.mime_type and part.file_data.mime_type.startswith("image/"):
                                 image = VertexImage.load_from_file(part.file_data.file_uri)
                             elif part.file_data.mime_type and part.file_data.mime_type.startswith("video/"):
                                 video = VertexVideo.load_from_file(part.file_data.file_uri)
                        
                        # types.Part might have 'file_uri' if created via from_uri (less common in V2 SDK)
                        if hasattr(part, "file_uri") and part.file_uri:
                             # Determine if image or video based on mime or uri?
                             # We try to inspect available attributes
                             mime = getattr(part, "mime_type", "")
                             if mime.startswith("image/"):
                                 image = VertexImage.load_from_file(part.file_uri)
                             elif mime.startswith("video/"):
                                 video = VertexVideo.load_from_file(part.file_uri)
                
                elif isinstance(content, str):
                    text = content

                embeddings = mm_model.get_embeddings(
                    image=image,
                    video=video,
                    contextual_text=text,
                )
                
                if image:
                    return embeddings.image_embedding
                elif video:
                    # video embeddings are segmented. Return the first one?
                    if embeddings.video_embeddings:
                        return embeddings.video_embeddings[0].embedding
                elif text:
                    return embeddings.text_embedding
                
                return None

            else:
                # Text Embedding using Vertex AI SDK
                model = TextEmbeddingModel.from_pretrained(model_name)
                # TextEmbeddingModel expects a list of Input objects or strings?
                # It accepts strings usually.
                if isinstance(content, str):
                    embeddings = model.get_embeddings([content])
                    if embeddings:
                        return embeddings[0].values
                return None
        except Exception as e:
            logger.error(f"Failed to generate embedding with model {model_name}: {e}")
            return None

