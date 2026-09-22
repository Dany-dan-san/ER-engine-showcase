# ============================================================
# Frozen RF2 scorer
#
# Expected RDS bundle:
#   bundle$model          -> randomForest classification model
#   bundle$predictor_cols -> character vector of 37 predictors
#   bundle$threshold      -> decision threshold, expected 0.51
#
# Called by Python as:
#   Rscript score_rf2.R \
#     <model.rds> \
#     <pairwise.csv> \
#     <predictors.csv> \
#     <output.csv> \
#     <default_threshold> \
#     <positive_class>
# ============================================================

args <- commandArgs(trailingOnly = TRUE)

if (length(args) != 6) {
  stop(
    paste(
      "Usage: Rscript score_rf2.R",
      "<model.rds> <pairwise.csv> <predictors.csv>",
      "<output.csv> <default_threshold> <positive_class>"
    )
  )
}

model_path <- args[[1]]
pairwise_path <- args[[2]]
predictor_path <- args[[3]]
output_path <- args[[4]]
default_threshold <- suppressWarnings(as.numeric(args[[5]]))
positive_class <- as.character(args[[6]])


# ============================================================
# Basic path and argument validation
# ============================================================

required_files <- c(
  "RDS model" = model_path,
  "pairwise input" = pairwise_path,
  "predictor-column file" = predictor_path
)

for (label in names(required_files)) {
  path <- required_files[[label]]

  if (!file.exists(path)) {
    stop(
      sprintf(
        "%s was not found: %s",
        label,
        path
      )
    )
  }
}

if (
  length(default_threshold) != 1 ||
  is.na(default_threshold) ||
  default_threshold < 0 ||
  default_threshold > 1
) {
  stop(
    "The supplied default threshold must be a number between 0 and 1."
  )
}

if (!nzchar(positive_class)) {
  stop("The positive class cannot be empty.")
}


# ============================================================
# Load the package required by the frozen model
# ============================================================

if (!requireNamespace("randomForest", quietly = TRUE)) {
  stop(
    paste(
      "The RF2 bundle contains a randomForest model, but the",
      "'randomForest' package is not installed in this R runtime.",
      "Install it with:",
      "install.packages('randomForest')"
    )
  )
}

suppressPackageStartupMessages(
  library(randomForest)
)


# ============================================================
# Restore and validate the exact frozen bundle
# ============================================================

bundle <- readRDS(model_path)

if (!is.list(bundle)) {
  stop(
    sprintf(
      "The RDS object must be a list; received class: %s",
      paste(class(bundle), collapse = "/")
    )
  )
}

required_bundle_fields <- c(
  "model",
  "predictor_cols",
  "threshold"
)

missing_bundle_fields <- setdiff(
  required_bundle_fields,
  names(bundle)
)

if (length(missing_bundle_fields) > 0) {
  stop(
    sprintf(
      "The RF2 bundle is missing required fields: %s",
      paste(missing_bundle_fields, collapse = ", ")
    )
  )
}

model <- bundle$model

if (!inherits(model, "randomForest")) {
  stop(
    sprintf(
      paste(
        "Expected bundle$model to inherit from 'randomForest';",
        "received class: %s"
      ),
      paste(class(model), collapse = "/")
    )
  )
}

if (
  is.null(model$type) ||
  !identical(as.character(model$type), "classification")
) {
  stop(
    sprintf(
      "The frozen RF2 model must be a classification model; model$type is %s.",
      paste(model$type, collapse = "/")
    )
  )
}

bundle_predictors <- trimws(
  as.character(bundle$predictor_cols)
)

bundle_predictors <- bundle_predictors[
  nzchar(bundle_predictors)
]

if (length(bundle_predictors) == 0) {
  stop("bundle$predictor_cols is empty.")
}

if (anyDuplicated(bundle_predictors)) {
  duplicated_predictors <- unique(
    bundle_predictors[
      duplicated(bundle_predictors)
    ]
  )

  stop(
    sprintf(
      "bundle$predictor_cols contains duplicates: %s",
      paste(duplicated_predictors, collapse = ", ")
    )
  )
}

if (length(bundle_predictors) != 37) {
  stop(
    sprintf(
      "The frozen RF2 bundle should contain 37 predictors; found %d.",
      length(bundle_predictors)
    )
  )
}

threshold <- suppressWarnings(
  as.numeric(bundle$threshold)
)

if (
  length(threshold) != 1 ||
  is.na(threshold) ||
  threshold < 0 ||
  threshold > 1
) {
  warning(
    paste(
      "bundle$threshold is missing or invalid;",
      sprintf(
        "using supplied default threshold %.6f instead.",
        default_threshold
      )
    )
  )

  threshold <- default_threshold
}

model_classes <- as.character(model$classes)

if (!positive_class %in% model_classes) {
  stop(
    sprintf(
      "Positive class '%s' is absent from model classes: %s",
      positive_class,
      paste(model_classes, collapse = ", ")
    )
  )
}


# ============================================================
# Validate model-side predictor names where available
# ============================================================

model_predictors <- NULL

if (
  !is.null(model$forest) &&
  !is.null(model$forest$ncat) &&
  !is.null(names(model$forest$ncat))
) {
  model_predictors <- names(model$forest$ncat)
} else if (
  !is.null(model$importance) &&
  !is.null(rownames(model$importance))
) {
  model_predictors <- rownames(model$importance)
}

if (
  !is.null(model_predictors) &&
  !identical(
    as.character(model_predictors),
    bundle_predictors
  )
) {
  stop(
    paste(
      "The predictor order stored in bundle$predictor_cols does not",
      "match the predictor order stored inside bundle$model."
    )
  )
}


# ============================================================
# Validate the external frozen predictor-column file
# ============================================================

external_predictor_table <- read.csv(
  predictor_path,
  check.names = FALSE,
  stringsAsFactors = FALSE,
  fileEncoding = "UTF-8"
)

if (!"predictor_cols" %in% names(external_predictor_table)) {
  stop(
    "The predictor CSV must contain a column named 'predictor_cols'."
  )
}

external_predictors <- trimws(
  as.character(
    external_predictor_table$predictor_cols
  )
)

external_predictors <- external_predictors[
  nzchar(external_predictors)
]

if (!identical(external_predictors, bundle_predictors)) {
  stop(
    paste(
      "The external predictor-column file does not exactly match",
      "bundle$predictor_cols in both names and order.",
      "",
      "Bundle order:",
      paste(bundle_predictors, collapse = ", "),
      "",
      "External-file order:",
      paste(external_predictors, collapse = ", "),
      sep = "\n"
    )
  )
}


# ============================================================
# Read the Python-generated street-blocked pairwise table
# ============================================================

pairwise <- read.csv(
  pairwise_path,
  check.names = FALSE,
  stringsAsFactors = FALSE,
  fileEncoding = "UTF-8"
)

identifier_columns <- c(
  "pair_key",
  "ID_1",
  "ID_2"
)

missing_identifiers <- setdiff(
  identifier_columns,
  names(pairwise)
)

if (length(missing_identifiers) > 0) {
  stop(
    sprintf(
      "The pairwise table is missing identifier columns: %s",
      paste(missing_identifiers, collapse = ", ")
    )
  )
}

missing_predictors <- setdiff(
  bundle_predictors,
  names(pairwise)
)

if (length(missing_predictors) > 0) {
  stop(
    sprintf(
      "The pairwise table is missing RF2 predictors: %s",
      paste(missing_predictors, collapse = ", ")
    )
  )
}

if (anyDuplicated(pairwise$pair_key)) {
  stop("The pairwise table contains duplicate pair_key values.")
}


# ============================================================
# Handle an empty pairwise table safely
# ============================================================

if (nrow(pairwise) == 0) {
  output <- pairwise[
    ,
    identifier_columns,
    drop = FALSE
  ]

  output$rf2_probability <- numeric(0)
  output$rf2_match <- integer(0)
  output$rf2_threshold <- numeric(0)

  write.csv(
    output,
    output_path,
    row.names = FALSE,
    fileEncoding = "UTF-8"
  )

  quit(
    save = "no",
    status = 0
  )
}


# ============================================================
# Construct the exact 37-column RF2 model matrix
# ============================================================

new_data <- pairwise[
  ,
  bundle_predictors,
  drop = FALSE
]

for (column_name in bundle_predictors) {
  original <- new_data[[column_name]]

  converted <- suppressWarnings(
    as.numeric(original)
  )

  conversion_failed <- (
    !is.na(original) &
    nzchar(trimws(as.character(original))) &
    is.na(converted)
  )

  if (any(conversion_failed)) {
    bad_values <- unique(
      original[conversion_failed]
    )

    stop(
      sprintf(
        "Predictor '%s' contains non-numeric values: %s",
        column_name,
        paste(
          head(bad_values, 10),
          collapse = ", "
        )
      )
    )
  }

  new_data[[column_name]] <- converted
}

columns_with_missing_values <- names(new_data)[
  vapply(
    new_data,
    anyNA,
    logical(1)
  )
]

if (length(columns_with_missing_values) > 0) {
  stop(
    sprintf(
      "RF2 input contains missing values in: %s",
      paste(
        columns_with_missing_values,
        collapse = ", "
      )
    )
  )
}

columns_with_non_finite_values <- names(new_data)[
  vapply(
    new_data,
    function(column) any(!is.finite(column)),
    logical(1)
  )
]

if (length(columns_with_non_finite_values) > 0) {
  stop(
    sprintf(
      "RF2 input contains infinite/non-finite values in: %s",
      paste(
        columns_with_non_finite_values,
        collapse = ", "
      )
    )
  )
}

if (!identical(names(new_data), bundle_predictors)) {
  stop(
    "The model matrix is not in the exact frozen RF2 predictor order."
  )
}


# ============================================================
# Score the positive duplicate class
# ============================================================

probability_matrix <- predict(
  model,
  newdata = new_data,
  type = "prob"
)

if (
  is.null(dim(probability_matrix)) ||
  is.null(colnames(probability_matrix)) ||
  !positive_class %in% colnames(probability_matrix)
) {
  returned_columns <- if (
    is.null(colnames(probability_matrix))
  ) {
    "<none>"
  } else {
    paste(
      colnames(probability_matrix),
      collapse = ", "
    )
  }

  stop(
    sprintf(
      paste(
        "The RF2 model did not return a probability column for",
        "positive class '%s'. Returned columns: %s"
      ),
      positive_class,
      returned_columns
    )
  )
}

positive_probability <- as.numeric(
  probability_matrix[
    ,
    positive_class
  ]
)

if (length(positive_probability) != nrow(pairwise)) {
  stop(
    sprintf(
      "RF2 returned %d probabilities for %d pairwise rows.",
      length(positive_probability),
      nrow(pairwise)
    )
  )
}

if (
  anyNA(positive_probability) ||
  any(
    !is.finite(positive_probability)
  ) ||
  any(
    positive_probability < 0 |
    positive_probability > 1
  )
) {
  stop(
    "RF2 returned missing, non-finite, or invalid probabilities."
  )
}


# ============================================================
# Return pair identifiers, probabilities, and thresholded class
# ============================================================

output <- pairwise[
  ,
  identifier_columns,
  drop = FALSE
]

output$rf2_probability <- positive_probability
output$rf2_match <- as.integer(
  positive_probability >= threshold
)
output$rf2_threshold <- rep(
  threshold,
  nrow(output)
)

write.csv(
  output,
  output_path,
  row.names = FALSE,
  fileEncoding = "UTF-8"
)

cat(
  sprintf(
    paste0(
      "RF2 scoring completed: %d pair(s), ",
      "positive class='%s', threshold=%.6f\n"
    ),
    nrow(output),
    positive_class,
    threshold
  )
)

