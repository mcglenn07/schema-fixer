"""A deterministic header-only baseline, with abstention on ambiguous matches."""

from schema_fixer.header_matching import rename_hints
from schema_fixer.mapping import Drop, DroppedColumn, FieldMapping, Mapping, Rename
from schema_fixer.models import ColumnProfile, TargetSchema


class BaselineProposer:
    def propose(self, schema: TargetSchema, columns: list[ColumnProfile]) -> Mapping:
        sources = [column.name for column in columns]
        absent = [name for name in schema.fields if name not in sources]
        extra = [name for name in sources if name not in schema.fields]
        hints = rename_hints(extra, absent)
        fields = []
        required, optional = [], []
        used = set()
        for target, spec in schema.fields.items():
            if target in sources:
                source, confidence = target, 1.0
                reason = "Exact header match; values still require validation."
            elif target in hints:
                source, confidence = hints[target]
                reason = (
                    "Mutual-best header similarity; this is not semantic certainty."
                )
            else:
                (required if spec.required else optional).append(target)
                continue
            used.add(source)
            fields.append(
                FieldMapping(
                    target=target,
                    sources=[source],
                    transform=Rename(name="rename"),
                    confidence=confidence,
                    reason=reason,
                )
            )
        return Mapping(
            fields=fields,
            drop=[
                DroppedColumn(
                    sources=[source],
                    transform=Drop(name="drop"),
                    confidence=0.0,
                    reason="Unmatched source; review before discarding any data.",
                )
                for source in sources
                if source not in used
            ],
            unmapped_required=required,
            unmapped_optional=optional,
        )
