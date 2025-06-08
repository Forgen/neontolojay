from typing import Any, Self

from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator
from pydantic_core import PydanticCustomError

from .graphconnection import GraphConnection


class CommonModel(BaseModel):
    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    _set_on_match: list[str] = PrivateAttr()
    _set_on_create: list[str] = PrivateAttr()
    _always_set: list[str] = PrivateAttr()
    _never_set: list[str] = PrivateAttr()

    def __init__(self, **data: dict):
        super().__init__(**data)
        self._set_prop_usage()

    @classmethod
    def _set_prop_usage(cls) -> None:
        cls._set_on_match, cls._set_on_match_no_aliases = cls._get_prop_usage(
            "set_on_match"
        )
        cls._set_on_create, cls._set_on_create_no_aliases = cls._get_prop_usage(
            "set_on_create"
        )
        cls._never_set, cls._never_set_no_aliases = cls._get_prop_usage("never_set")
        cls._always_set = []
        cls._always_set_no_aliases = []
        for x, v in cls.model_fields.items():
            if x not in (
                cls._set_on_match_no_aliases
                + cls._set_on_create_no_aliases
                + cls._never_set_no_aliases
                + ["source", "target"]
            ):
                cls._always_set.append(v.alias if v.alias else x)
                cls._always_set_no_aliases.append(x)

    @classmethod
    def _get_prop_usage(
        cls,
        usage_type: str,
    ) -> tuple[list[str], list[str]]:
        all_props = cls.model_fields

        selected_props = []
        selected_props_no_aliases = []

        for prop, entry in all_props.items():
            if (
                entry.json_schema_extra
                and entry.json_schema_extra.get(usage_type) is True
            ):
                selected_props.append(entry.alias if entry.alias else prop)
                selected_props_no_aliases.append(prop)

        return (selected_props, selected_props_no_aliases)

    def _get_prop_values(
        self, props: list[str], exclude: set[str] = set()
    ) -> dict[str, Any]:
        """

        Returns:
            dict[str, Any]: a dictionary of key/value pairs.
        """

        # prop_values = {
        #    k: v for k, v in self._engine_dict(exclude=exclude).items() if k in props
        # }

        return self._engine_dict(exclude=exclude, include=set(props))

    def _engine_dict(
        self, exclude: set[str] = set(), by_alias: bool = True, **kwargs: Any
    ) -> dict[str, Any]:
        """Return a dict made up of only types compatible with the GraphEngine

        Returns:
            dict: a dictionary export of this model instance
        """
        excludes = exclude | set(self._never_set)
        if getattr(self, "__primaryproperty__", False):
            excludes.discard(self.__primaryproperty__)
        # ToDo: this should be exclude_none=True. This may be related to #13.
        pydantic_export_dict = self.model_dump(
            exclude_none=True, exclude=excludes, by_alias=by_alias, **kwargs
        )

        # return pydantic_export_dict

        try:
            gc = GraphConnection()
            export_dict = gc.engine.export_dict_converter(pydantic_export_dict)

        except RuntimeError:
            export_dict = pydantic_export_dict

        return export_dict

    def _get_merge_parameters_common(
        self, exclude: set[str] = set(), by_alias: bool = True
    ) -> dict[str, Any]:
        """Input an all properties dictionary, and filter based on property types.

        Returns:
            Dict[str, Any]: Dictionary of always_set, set_on_match, and set_on_create dictionaries
        """
        # get all the properties
        all_props = self._engine_dict(exclude=exclude, by_alias=by_alias)

        if by_alias:
            always_set = {
                k: all_props[k]
                for k in self._always_set
                if (k in all_props and all_props[k] is not None)
            }
            set_on_match = {
                k: all_props[k] for k in self._set_on_match if k in all_props
            }
            set_on_create = {
                k: all_props[k] for k in self._set_on_create if k in all_props
            }
        else:
            always_set = {
                k: all_props[k]
                for k in self._always_set_no_aliases
                if (k in all_props and all_props[k] is not None)
            }
            set_on_match = {
                k: all_props[k] for k in self._set_on_match_no_aliases if k in all_props
            }
            set_on_create = {
                k: all_props[k]
                for k in self._set_on_create_no_aliases
                if k in all_props
            }
        params = {
            "all_props": all_props,
            "always_set": always_set,
            "set_on_match": set_on_match,
            "set_on_create": set_on_create,
        }
        return params

    #
    # validators
    #

    @model_validator(mode="before")
    @classmethod
    def deprecated_merged_created(cls, data: Any) -> Any:
        """Neontology v0 and v1 included and auto-populated this property.
        Flag a warning whe
            temporarily supported/deprecated before being removed.
        """

        if ("created" in data and "created" not in cls.model_fields) or (
            "merged" in data and "merged" not in cls.model_fields
        ):
            raise PydanticCustomError(
                "created_or_merged_fields",
                (
                    "Native neontology support for 'merged' and 'created' properties has been removed."
                    " Consider adding these fields to your model(s) and read the docs for further info"
                ),
            )
        return data

    def check_sync_result(self, result: Self) -> None:
        """Checks that a returned result matches the current object based on always_set properties.
        Synchronizes result.element_id to self if applicable.
        Synchronizes result.properties to self if self.property = None (i.e. not specified).
        Synchronizes result.properties to self if property set_on_match or set_on_create.

        Raises ValueError if self and result do not match"""
        if not isinstance(result, type(self)):
            raise ValueError(f"Result type is {type(result)}; expected {type(self)}.")
        result_merge_parameters = result._get_merge_parameters_common(
            by_alias=False, exclude={"source", "target"}
        )
        result_prop_keys: dict = (
            result_merge_parameters["always_set"]
            | result_merge_parameters["set_on_create"]
            | result_merge_parameters["set_on_match"]
        )
        self_merge_parameters = self._get_merge_parameters_common(
            by_alias=False, exclude={"source", "target"}
        )
        self_prop_keys: dict = (
            self_merge_parameters["always_set"]
            | self_merge_parameters["set_on_create"]
            | self_merge_parameters["set_on_match"]
        )
        self_always_set = self_merge_parameters["always_set"]
        all_prop_keys = self_prop_keys.keys() | result_prop_keys.keys()
        for k in all_prop_keys:
            if k not in self_always_set:
                setattr(self, k, result_prop_keys.get(k, None))
            elif k not in result_prop_keys or (
                k in self_always_set and self_always_set[k] != result_prop_keys[k]
            ):
                raise ValueError(
                    f"Resulting {type(self)} {result.__repr__} does not match the calling object {self.__repr__}."
                )
        elementidproperty = getattr(self, "__elementidproperty__", None)
        if elementidproperty:  # copy element id from result to self
            setattr(self, elementidproperty, getattr(result, elementidproperty))
