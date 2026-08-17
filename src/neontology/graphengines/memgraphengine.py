from typing import TYPE_CHECKING, Any, ClassVar, List, Optional

from neo4j import GraphDatabase
from neo4j import Result as Neo4jResult

from ..gql import gql_identifier_adapter
from ..result import NeontologyResult
from .graphengine import GraphEngineBase, GraphEngineConfig
from .neo4jengine import neo4j_records_to_neontology_records

if TYPE_CHECKING:
    from ..basenode import BaseNode
    from ..baserelationship import BaseRelationship


class MemgraphEngine(GraphEngineBase):
    """Graph engine for a Memgraph database.

    Note. the memgraph engine is very similar to the Neo4j engine as they
        can both use the same Neo4j driver
    """

    def __init__(self, config: "MemgraphConfig") -> None:
        """Initialise connection to the Memgraph database.

        Args:
            config (MemgraphConfig): Takes a MemgraphConfig object.
        """
        self.driver = GraphDatabase.driver(
            config.connection_uri,
            auth=(config.connection_username, config.connection_password),
        )

    def verify_connection(self) -> bool:
        """Verify the connection to the Memgraph database.

        Returns:
            bool: True if the connection is successful, False otherwise.
        """
        try:
            self.driver.verify_connectivity()
            return True
        except:  # noqa: E722
            return False

    def close_connection(self) -> None:
        """Close the connection to the Memgraph database."""
        try:
            self.driver.close()
        except AttributeError:
            pass

    def evaluate_query(
        self,
        cypher: str,
        params: dict = {},
        node_classes: dict = {},
        relationship_classes: dict = {},
    ) -> NeontologyResult:
        """Evaluate a Cypher query and return the results as Neontology records.

        Args:
            cypher (str): query to evaluate.
            params (dict, optional): parameters to pass through. Defaults to {}.
            node_classes (dict, optional): mapping of labels to node classes used for populating with results. Defaults to {}.
            relationship_classes (dict, optional): mapping of relationship types to classes used for populating with results.
                Defaults to {}.

        Returns:
            NeontologyResult: Result object containing the records, nodes, relationships, and paths.
        """
        result = self.driver.execute_query(cypher, parameters_=params)

        neo4j_records = result.records
        neontology_records, nodes, rels, paths = neo4j_records_to_neontology_records(
            neo4j_records, node_classes, relationship_classes
        )

        return NeontologyResult(
            records_raw=neo4j_records,
            records=neontology_records,
            nodes=nodes,
            relationships=rels,
            paths=paths,
        )

    def evaluate_query_single(self, cypher: str, params: dict = {}) -> Optional[Any]:
        """Evaluate a Cypher query which returns a single result.

        Args:
            cypher (str): query to evaluate.
            params (dict, optional): parameters to pass through. Defaults to {}.

        Returns:
            Optional[Any]: Query result, or None if no result is found.
        """
        result = self.driver.execute_query(cypher, parameters_=params, result_transformer_=Neo4jResult.single)

        if result:
            return result.value()

        else:
            return None

    def match_node(self, pp: str, node_class: type["BaseNode"]) -> Optional["BaseNode"]:
        """MATCH a single node of this type with the given primary property.
        Memgraph specific element id function version

        Args:
            pp (str): The value of the primary property (pp) to match on.
            node_class (type[BaseNode]): Class of the node to match

        Returns:
            Optional[B]: If the node exists, return it as an instance.
        """
        element_id_prop_name = getattr(node_class, "__elementidproperty__", None)
        if node_class.__primaryproperty__ == element_id_prop_name:
            match_cypher = "toString(id(n))"
        else:
            match_cypher = f"n.{node_class.__primaryproperty__}"

        cypher = f"""
        MATCH (n:{node_class.__primarylabel__})
        WHERE {match_cypher} = $pp
        RETURN n
        """

        params = {"pp": pp}

        result = self.evaluate_query(
            cypher, params, node_classes={node_class.__primarylabel__: node_class}
        )

        if result.nodes:
            return result.nodes[0]

        else:
            return None

    @staticmethod
    def _where_elementId_cypher() -> str:
        return "toString(id(n)) = $pp"

    def merge_relationships(
        self,
        source_label: str,
        target_label: str,
        source_prop: str,
        target_prop: str,
        rel_type: str,
        merge_on_props: List[str],
        rel_props: List[dict],
        rel_class: type["BaseRelationship"],
    ) -> NeontologyResult:
        """Merge relationships - memgraph specific element id function version"""
        # build a string of properties to merge on "prop_name: $prop_name"
        merge_props = ", ".join(
            [
                f"{gql_identifier_adapter.validate_strings(x)}: rel.{x}"
                for x in merge_on_props
            ]
        )

        if rel_props[0]["source_element_id_prop"] == source_prop:
            source_match_cypher = """toString(id(source))"""
        else:
            source_match_cypher = (
                f"""source.{gql_identifier_adapter.validate_strings(source_prop)}"""
            )
        if rel_props[0]["target_element_id_prop"] == target_prop:
            target_match_cypher = """toString(id(target))"""
        else:
            target_match_cypher = (
                f"""target.{gql_identifier_adapter.validate_strings(target_prop)}"""
            )
        cypher = f"""
        UNWIND $rel_list AS rel
        MATCH (source:{gql_identifier_adapter.validate_strings(source_label)})
        WHERE {source_match_cypher} = rel.source_prop
        MATCH (target:{gql_identifier_adapter.validate_strings(target_label)})
        WHERE {target_match_cypher} = rel.target_prop
        MERGE (source)-[r:{gql_identifier_adapter.validate_strings(rel_type)} {{ {merge_props} }}]->(target)
        ON MATCH SET r += rel.set_on_match
        ON CREATE SET r += rel.set_on_create
        SET r += rel.always_set
        RETURN r, source, target
        """

        params = {"rel_list": rel_props}

        from ..utils import get_node_types, get_rels_by_type

        rel_types = get_rels_by_type(rel_class)
        node_classes = get_node_types(rel_class.model_fields["source"].annotation)
        if (
            rel_class.model_fields["source"].annotation
            != rel_class.model_fields["target"].annotation
        ):
            node_classes.update(
                get_node_types(rel_class.model_fields["target"].annotation)
            )

        return self.evaluate_query(
            cypher, params, node_classes=node_classes, relationship_classes=rel_types
        )


class MemgraphConfig(GraphEngineConfig):
    """Configuration for a Neo4j graph engine."""

    engine: ClassVar[type[MemgraphEngine]] = MemgraphEngine
    uri: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    env_fields: ClassVar[dict[str, str]] = {
        "uri": "MEMGRAPH_URI",
        "username": "MEMGRAPH_USERNAME",
        "password": "MEMGRAPH_PASSWORD",
    }

    # Properties that guarantee non-None values for type checking
    @property
    def connection_uri(self) -> str:
        """Get the URI, guaranteed to be non-None after validation."""
        if self.uri is None:
            raise ValueError("URI should be set by validator")

        return self.uri

    @property
    def connection_username(self) -> str:
        """Get the username, guaranteed to be non-None after validation."""
        if self.username is None:
            raise ValueError("Username should be set by validator")

        return self.username

    @property
    def connection_password(self) -> str:
        """Get the password, guaranteed to be non-None after validation."""
        if self.password is None:
            raise ValueError("Password should be set by validator")

        return self.password
