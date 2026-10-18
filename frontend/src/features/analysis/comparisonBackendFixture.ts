/* Serialized with backend ComparisonResult.model_dump(mode="json") on synthetic data. */
export const comparisonBackendFixture = {
  "source": {
    "kind": "prepared_dataset_version",
    "schema_version": 1,
    "dataset_id": "prepared1",
    "structure_id": "s1",
    "dataset_version": 1,
    "file_id": "f1",
    "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "dataset_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "dataset_size_bytes": 100,
    "dataset_schema_version": 1,
    "sheet_index": 0,
    "sheet_name": "Sheet1",
    "parser_version": "openpyxl-3.1.5-structure-v1",
    "parent_dataset_id": "raw1",
    "parent_dataset_version": 1,
    "transform_version": "excel_prepare_v1"
  },
  "analysis_plan": {
    "plan_id": "plan3",
    "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "resolutions": {}
  },
  "schema_version": 4,
  "result_type": "group_comparison",
  "id": "run4",
  "file_id": "f1",
  "filename": "synthetic.xlsx",
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "setup_revision": 2,
  "selection": {
    "task_type": "group_comparison",
    "sheet_name": "Sheet1",
    "design": "independent",
    "method": "welch_t",
    "numeric_column": "C",
    "group_column": "D",
    "groups": [
      {
        "kind": "text",
        "value": "Treatment"
      },
      {
        "kind": "text",
        "value": "Control"
      }
    ],
    "pair_id_column": null,
    "before_column": null,
    "after_column": null,
    "unit": "kg",
    "missing_policy": "complete_cases",
    "posthoc": "none",
    "assumptions": {
      "independent_units": true,
      "distribution": "normal",
      "inference_confirmed": true
    }
  },
  "check": {
    "ready": true,
    "row_count": 7,
    "valid_count": 6,
    "excluded_count": 1,
    "groups": [
      {
        "label": "Treatment",
        "count": 3
      },
      {
        "label": "Control",
        "count": 3
      }
    ],
    "issues": [],
    "warnings": []
  },
  "engine": {
    "id": "group_comparison_statistics_dataset_v1",
    "python_version": "3.11",
    "scipy_version": "1.17.1",
    "numpy_version": "2.4.6",
    "parser_version": "openpyxl-3.1.5-structure-v1"
  },
  "started_at": "2026-10-08T01:00:00Z",
  "completed_at": "2026-10-08T01:00:00Z",
  "variables": [
    {
      "column": "C",
      "name": "Weight",
      "unit": "kg"
    }
  ],
  "groups": [
    {
      "label": "Treatment",
      "statistics": {
        "n": 3,
        "mean": 3.0,
        "std": 1.0,
        "min": 2.0,
        "q1": 2.5,
        "median": 3.0,
        "q3": 3.5,
        "max": 4.0,
        "iqr": 1.0,
        "warnings": []
      }
    },
    {
      "label": "Control",
      "statistics": {
        "n": 3,
        "mean": 3.0,
        "std": 1.0,
        "min": 2.0,
        "q1": 2.5,
        "median": 3.0,
        "q3": 3.5,
        "max": 4.0,
        "iqr": 1.0,
        "warnings": []
      }
    }
  ],
  "statistics": {
    "method": "welch_t",
    "design": "independent",
    "sample_sizes": [
      3,
      3
    ],
    "statistic": {
      "name": "t",
      "value": 0.0,
      "df_numerator": null,
      "df_denominator": 4.0
    },
    "estimate": {
      "name": "mean_difference",
      "value": 0.0,
      "unit": "outcome",
      "reason": null
    },
    "p_value": {
      "value": 1.0,
      "method": "welch_t_two_sided"
    },
    "confidence_interval": {
      "low": -2.267,
      "high": 2.267,
      "level": 0.95,
      "method": "welch_t",
      "reason": null,
      "simultaneous": false
    },
    "inference": {
      "alternative": "two-sided",
      "rank_method": null,
      "zero_method": null,
      "continuity_correction": false,
      "exact": false,
      "zero_count": 0
    },
    "family": {
      "policy": "none",
      "size": 0,
      "alpha": 0.05
    },
    "pairwise": [],
    "warnings": [
      "observational_not_causal"
    ]
  },
  "row_audit": {
    "included_rows": [
      2,
      3,
      4,
      5,
      6,
      7
    ],
    "excluded_rows": [
      {
        "row": 8,
        "coordinates": [
          "D8"
        ],
        "reason": "group_not_selected"
      }
    ],
    "missing_policy": "complete_cases",
    "group_rows": [
      [
        2,
        3,
        4
      ],
      [
        5,
        6,
        7
      ]
    ],
    "pair_id_column": null
  },
  "analysis_context": {
    "plan": {
      "schema_version": 3,
      "workflow_version": "analysis_plan_v3",
      "rules_version": "analysis_plan_rules_v3",
      "id": "plan3",
      "task_id": "t1",
      "decision_id": "decision3",
      "project_id": "p1",
      "file_id": "f1",
      "source": {
        "kind": "prepared_dataset_version",
        "schema_version": 1,
        "dataset_id": "prepared1",
        "structure_id": "s1",
        "dataset_version": 1,
        "file_id": "f1",
        "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "dataset_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "dataset_size_bytes": 100,
        "dataset_schema_version": 1,
        "sheet_index": 0,
        "sheet_name": "Sheet1",
        "parser_version": "openpyxl-3.1.5-structure-v1",
        "parent_dataset_id": "raw1",
        "parent_dataset_version": 1,
        "transform_version": "excel_prepare_v1"
      },
      "selection": {
        "task_type": "group_comparison",
        "sheet_name": "Sheet1",
        "design": "independent",
        "method": "welch_t",
        "numeric_column": "C",
        "group_column": "D",
        "groups": [
          {
            "kind": "text",
            "value": "Treatment"
          },
          {
            "kind": "text",
            "value": "Control"
          }
        ],
        "pair_id_column": null,
        "before_column": null,
        "after_column": null,
        "unit": "kg",
        "missing_policy": "complete_cases",
        "posthoc": "none",
        "assumptions": {
          "independent_units": true,
          "distribution": "normal",
          "inference_confirmed": true
        }
      },
      "check": {
        "rules_version": "analysis_plan_rules_v3",
        "data_range": "C5:D10",
        "row_count": 7,
        "selected_fields": [
          {
            "letter": "C",
            "name": "weight",
            "type_counts": {
              "number": 4,
              "blank": 2
            },
            "missing_count": 2,
            "non_missing_count": 4,
            "prepared_unit": {
              "status": "unconfirmed",
              "value": null
            },
            "declared_unit": {
              "status": "unknown",
              "value": null
            },
            "observed_min": 3.0,
            "observed_max": 8.0
          }
        ],
        "selection_check": {
          "ready": true,
          "row_count": 7,
          "valid_count": 6,
          "excluded_count": 1,
          "groups": [
            {
              "label": "Treatment",
              "count": 3
            },
            {
              "label": "Control",
              "count": 3
            }
          ],
          "issues": [],
          "warnings": []
        },
        "issues": [],
        "limitations": [
          "observed only"
        ],
        "research_missing": []
      },
      "resolutions": {},
      "plan_revision": 1,
      "setup_revision": 2,
      "created_at": "2026-10-08T01:00:00Z",
      "research_request": {
        "question": "private original question",
        "output_language": "en",
        "population": "Synthetic participants",
        "study_design": "Cross-sectional",
        "observation_unit": "One row per participant",
        "observation_structure": "independent",
        "relationship_description": "",
        "output_requirements": ""
      },
      "recommendation_ref": null,
      "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    },
    "method": {
      "id": "welch_t",
      "parameters": {
        "task_type": "group_comparison",
        "sheet_name": "Sheet1",
        "design": "independent",
        "method": "welch_t",
        "numeric_column": "C",
        "group_column": "D",
        "groups": [
          {
            "kind": "text",
            "value": "Treatment"
          },
          {
            "kind": "text",
            "value": "Control"
          }
        ],
        "pair_id_column": null,
        "before_column": null,
        "after_column": null,
        "unit": "kg",
        "missing_policy": "complete_cases",
        "posthoc": "none",
        "assumptions": {
          "independent_units": true,
          "distribution": "normal",
          "inference_confirmed": true
        }
      },
      "observation_basis": "independent_rows"
    },
    "rounding": {
      "display_significant_digits": 6,
      "stored_values": "full_precision"
    }
  }
}
