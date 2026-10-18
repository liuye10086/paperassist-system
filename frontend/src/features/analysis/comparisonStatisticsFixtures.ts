export const comparisonStatisticsFixtures = {
  "welch_t": {
    "method": "welch_t",
    "design": "independent",
    "sample_sizes": [
      5,
      5
    ],
    "statistic": {
      "name": "t",
      "value": -1.1595018087284055,
      "df_numerator": null,
      "df_denominator": 7.724401001311241
    },
    "estimate": {
      "name": "mean_difference",
      "value": -2.1999999999999997,
      "unit": "outcome",
      "reason": null
    },
    "p_value": {
      "value": 0.2808354331633654,
      "method": "welch_t_two_sided"
    },
    "confidence_interval": {
      "low": -6.602657375157532,
      "high": 2.2026573751575333,
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
      "observational_not_causal",
      "small_sample"
    ]
  },
  "mann_whitney_u": {
    "method": "mann_whitney_u",
    "design": "independent",
    "sample_sizes": [
      5,
      5
    ],
    "statistic": {
      "name": "U",
      "value": 7.0,
      "df_numerator": null,
      "df_denominator": null
    },
    "estimate": {
      "name": "rank_biserial",
      "value": -0.43999999999999995,
      "unit": "dimensionless",
      "reason": null
    },
    "p_value": {
      "value": 0.2933255737660211,
      "method": "mann_whitney_asymptotic_two_sided"
    },
    "confidence_interval": {
      "low": null,
      "high": null,
      "level": 0.95,
      "method": null,
      "reason": "rank_interval_not_implemented",
      "simultaneous": false
    },
    "inference": {
      "alternative": "two-sided",
      "rank_method": "average",
      "zero_method": null,
      "continuity_correction": true,
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
      "observational_not_causal",
      "small_sample",
      "asymptotic_p_value",
      "rank_interval_unavailable"
    ]
  },
  "paired_t": {
    "method": "paired_t",
    "design": "paired",
    "sample_sizes": [
      5,
      5
    ],
    "statistic": {
      "name": "t",
      "value": -5.879747322073336,
      "df_numerator": null,
      "df_denominator": 4.0
    },
    "estimate": {
      "name": "mean_difference",
      "value": -2.1999999999999997,
      "unit": "outcome",
      "reason": null
    },
    "p_value": {
      "value": 0.0041810721356403,
      "method": "paired_t_two_sided"
    },
    "confidence_interval": {
      "low": -3.2388506336835676,
      "high": -1.1611493663164323,
      "level": 0.95,
      "method": "paired_t",
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
      "observational_not_causal",
      "small_sample"
    ]
  },
  "wilcoxon": {
    "method": "wilcoxon",
    "design": "paired",
    "sample_sizes": [
      5,
      5
    ],
    "statistic": {
      "name": "W",
      "value": 0.0,
      "df_numerator": null,
      "df_denominator": null
    },
    "estimate": {
      "name": "rank_biserial",
      "value": -1.0,
      "unit": "dimensionless",
      "reason": null
    },
    "p_value": {
      "value": 0.0625,
      "method": "wilcoxon_sign_exact_two_sided"
    },
    "confidence_interval": {
      "low": null,
      "high": null,
      "level": 0.95,
      "method": null,
      "reason": "rank_interval_not_implemented",
      "simultaneous": false
    },
    "inference": {
      "alternative": "two-sided",
      "rank_method": "average",
      "zero_method": "wilcox",
      "continuity_correction": false,
      "exact": true,
      "zero_count": 0
    },
    "family": {
      "policy": "none",
      "size": 0,
      "alpha": 0.05
    },
    "pairwise": [],
    "warnings": [
      "observational_not_causal",
      "small_sample",
      "rank_interval_unavailable"
    ]
  },
  "welch_anova": {
    "method": "welch_anova",
    "design": "multiple",
    "sample_sizes": [
      5,
      5,
      5
    ],
    "statistic": {
      "name": "F",
      "value": 2.9885713319510234,
      "df_numerator": 2.0,
      "df_denominator": 7.781385549687169
    },
    "estimate": {
      "name": null,
      "value": null,
      "unit": null,
      "reason": "omnibus_no_single_effect"
    },
    "p_value": {
      "value": 0.10889175673487372,
      "method": "welch_anova_f"
    },
    "confidence_interval": {
      "low": null,
      "high": null,
      "level": 0.95,
      "method": null,
      "reason": "omnibus_no_interval",
      "simultaneous": false
    },
    "inference": {
      "alternative": "omnibus",
      "rank_method": null,
      "zero_method": null,
      "continuity_correction": false,
      "exact": false,
      "zero_count": 0
    },
    "family": {
      "policy": "all_pairs_holm",
      "size": 3,
      "alpha": 0.05
    },
    "pairwise": [
      {
        "left_index": 0,
        "right_index": 1,
        "method": "welch_t",
        "statistic": {
          "name": "t",
          "value": -1.1595018087284055,
          "df_numerator": null,
          "df_denominator": 7.724401001311241
        },
        "estimate": {
          "name": "mean_difference",
          "value": -2.1999999999999997,
          "unit": "outcome",
          "reason": null
        },
        "p_value": {
          "value": 0.2808354331633654,
          "method": "welch_t_two_sided"
        },
        "confidence_interval": {
          "low": -6.602657375157532,
          "high": 2.2026573751575333,
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
        "adjusted_p_value": 0.3800014798953882,
        "adjustment": "holm"
      },
      {
        "left_index": 0,
        "right_index": 2,
        "method": "welch_t",
        "statistic": {
          "name": "t",
          "value": -2.5298221281347035,
          "df_numerator": null,
          "df_denominator": 6.877094492023026
        },
        "estimate": {
          "name": "mean_difference",
          "value": -5.6,
          "unit": "outcome",
          "reason": null
        },
        "p_value": {
          "value": 0.039819838348449814,
          "method": "welch_t_two_sided"
        },
        "confidence_interval": {
          "low": -10.85334226313456,
          "high": -0.346657736865438,
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
        "adjusted_p_value": 0.11945951504534943,
        "adjustment": "holm"
      },
      {
        "left_index": 1,
        "right_index": 2,
        "method": "welch_t",
        "statistic": {
          "name": "t",
          "value": -1.4393347726688253,
          "df_numerator": null,
          "df_denominator": 7.588136378037191
        },
        "estimate": {
          "name": "mean_difference",
          "value": -3.3999999999999986,
          "unit": "outcome",
          "reason": null
        },
        "p_value": {
          "value": 0.1900007399476941,
          "method": "welch_t_two_sided"
        },
        "confidence_interval": {
          "low": -8.899144066277875,
          "high": 2.099144066277878,
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
        "adjusted_p_value": 0.3800014798953882,
        "adjustment": "holm"
      }
    ],
    "warnings": [
      "observational_not_causal",
      "small_sample",
      "pairwise_intervals_unadjusted"
    ]
  },
  "kruskal_wallis": {
    "method": "kruskal_wallis",
    "design": "multiple",
    "sample_sizes": [
      5,
      5,
      5
    ],
    "statistic": {
      "name": "H",
      "value": 4.394234234234231,
      "df_numerator": 2.0,
      "df_denominator": null
    },
    "estimate": {
      "name": null,
      "value": null,
      "unit": null,
      "reason": "omnibus_no_single_effect"
    },
    "p_value": {
      "value": 0.11112305177701778,
      "method": "kruskal_chi_square"
    },
    "confidence_interval": {
      "low": null,
      "high": null,
      "level": 0.95,
      "method": null,
      "reason": "omnibus_no_interval",
      "simultaneous": false
    },
    "inference": {
      "alternative": "omnibus",
      "rank_method": "average",
      "zero_method": null,
      "continuity_correction": false,
      "exact": false,
      "zero_count": 0
    },
    "family": {
      "policy": "all_pairs_holm",
      "size": 3,
      "alpha": 0.05
    },
    "pairwise": [
      {
        "left_index": 0,
        "right_index": 1,
        "method": "mann_whitney_u",
        "statistic": {
          "name": "U",
          "value": 7.0,
          "df_numerator": null,
          "df_denominator": null
        },
        "estimate": {
          "name": "rank_biserial",
          "value": -0.43999999999999995,
          "unit": "dimensionless",
          "reason": null
        },
        "p_value": {
          "value": 0.2933255737660211,
          "method": "mann_whitney_asymptotic_two_sided"
        },
        "confidence_interval": {
          "low": null,
          "high": null,
          "level": 0.95,
          "method": null,
          "reason": "rank_interval_not_implemented",
          "simultaneous": false
        },
        "inference": {
          "alternative": "two-sided",
          "rank_method": "average",
          "zero_method": null,
          "continuity_correction": true,
          "exact": false,
          "zero_count": 0
        },
        "adjusted_p_value": 0.49830527716385364,
        "adjustment": "holm"
      },
      {
        "left_index": 0,
        "right_index": 2,
        "method": "mann_whitney_u",
        "statistic": {
          "name": "U",
          "value": 3.5,
          "df_numerator": null,
          "df_denominator": null
        },
        "estimate": {
          "name": "rank_biserial",
          "value": -0.72,
          "unit": "dimensionless",
          "reason": null
        },
        "p_value": {
          "value": 0.07491289930444599,
          "method": "mann_whitney_asymptotic_two_sided"
        },
        "confidence_interval": {
          "low": null,
          "high": null,
          "level": 0.95,
          "method": null,
          "reason": "rank_interval_not_implemented",
          "simultaneous": false
        },
        "inference": {
          "alternative": "two-sided",
          "rank_method": "average",
          "zero_method": null,
          "continuity_correction": true,
          "exact": false,
          "zero_count": 0
        },
        "adjusted_p_value": 0.22473869791333795,
        "adjustment": "holm"
      },
      {
        "left_index": 1,
        "right_index": 2,
        "method": "mann_whitney_u",
        "statistic": {
          "name": "U",
          "value": 6.5,
          "df_numerator": null,
          "df_denominator": null
        },
        "estimate": {
          "name": "rank_biserial",
          "value": -0.48,
          "unit": "dimensionless",
          "reason": null
        },
        "p_value": {
          "value": 0.24915263858192682,
          "method": "mann_whitney_asymptotic_two_sided"
        },
        "confidence_interval": {
          "low": null,
          "high": null,
          "level": 0.95,
          "method": null,
          "reason": "rank_interval_not_implemented",
          "simultaneous": false
        },
        "inference": {
          "alternative": "two-sided",
          "rank_method": "average",
          "zero_method": null,
          "continuity_correction": true,
          "exact": false,
          "zero_count": 0
        },
        "adjusted_p_value": 0.49830527716385364,
        "adjustment": "holm"
      }
    ],
    "warnings": [
      "observational_not_causal",
      "small_sample",
      "asymptotic_p_value",
      "rank_interval_unavailable"
    ]
  }
}
