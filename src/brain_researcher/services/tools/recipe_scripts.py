"""Per-analysis Python / shell script generators for public MCP tool recipes.

Carved out of ``mcp/execution_recipes.py``: the pure string-building generators
for the per-analysis runtime scripts (GLM first/second level, connectivity
matrix, seed-based connectivity, MVPA, temporal decoding, encoding models,
searchlight, rest-connectome, the preprocessing post-QC / neurodesk / container
scripts, the direct-family dispatcher, and the default runtime script).

These are self-contained pure functions (no dependency on other
``execution_recipes`` functions or globals), consumed by the recipe builders.
``execution_recipes`` re-exports them so existing importers keep resolving.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Any


def _default_runtime_script(tool_id: str) -> str:
    return (
        "import json\n"
        "from pathlib import Path\n\n"
        "from brain_researcher.services.tools.executor import execute_tool\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        f'result = execute_tool("{tool_id}", params)\n'
        'print(json.dumps(result.model_dump(mode="python"), indent=2, sort_keys=True, default=str))\n'
    )


def _glm_first_level_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd
        from nilearn.glm.first_level import FirstLevelModel
        from nilearn.image import load_img


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        img_path = Path(params["img"]).expanduser().resolve()
        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "glm_first_level")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        img = load_img(str(img_path))
        t_r = params.get("t_r")
        if t_r is None:
            zooms = img.header.get_zooms()
            t_r = float(zooms[3]) if len(zooms) >= 4 else 2.0

        events_path = params.get("events")
        if events_path:
            events_file = Path(events_path).expanduser().resolve()
            sep = "\\t" if events_file.suffix.lower() == ".tsv" else ","
            events = pd.read_csv(events_file, sep=sep)
        else:
            n_scans = int(img.shape[3])
            events = pd.DataFrame(
                {
                    "onset": [0.0],
                    "duration": [float(n_scans) * float(t_r)],
                    "trial_type": ["stim"],
                }
            )

        model = FirstLevelModel(
            t_r=float(t_r),
            hrf_model=str(params.get("hrf_model", "spm")),
            drift_model=str(params.get("drift_model", "cosine")),
            high_pass=float(params.get("high_pass", 0.01)),
            mask_img=params.get("mask_img"),
            smoothing_fwhm=params.get("smoothing_fwhm"),
            standardize=bool(params.get("standardize", True)),
            noise_model=str(params.get("noise_model", "ar1")),
            n_jobs=int(params.get("n_jobs", -1)),
        ).fit(str(img_path), events)

        design_matrix = model.design_matrices_[0]
        contrasts = params.get("contrasts") or {}
        if not contrasts:
            usable_columns = [
                column
                for column in design_matrix.columns
                if column.lower() not in {"constant", "intercept"}
            ]
            for column in usable_columns:
                vector = np.zeros(len(design_matrix.columns), dtype=float)
                vector[design_matrix.columns.get_loc(column)] = 1.0
                contrasts[column] = vector.tolist()

        zmaps = []
        for name, contrast in contrasts.items():
            contrast_def = (
                np.asarray(contrast, dtype=float)
                if isinstance(contrast, (list, tuple))
                else contrast
            )
            z_map = model.compute_contrast(contrast_def, output_type="z_score")
            zmap_path = output_dir / f"{name}_zmap.nii.gz"
            z_map.to_filename(zmap_path)
            zmaps.append(str(zmap_path))

        summary = {
            "hrf_model": str(params.get("hrf_model", "spm")),
            "noise_model": str(params.get("noise_model", "ar1")),
            "contrasts": list(contrasts.keys()),
            "design_columns": list(design_matrix.columns),
            "n_scans": int(design_matrix.shape[0]),
            "used_nilearn_package": True,
        }
        summary_path = output_dir / "glm_first_level_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print(
            json.dumps(
                {
                    "outputs": {
                        "summary": str(summary_path),
                        "zmaps": zmaps,
                    },
                    "summary": summary,
                    "message": "First-level GLM completed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """
    ).lstrip()


def _glm_second_level_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd
        from nilearn.glm.second_level import SecondLevelModel


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        contrast_maps = [
            str(Path(path).expanduser().resolve())
            for path in params.get("contrast_maps", [])
        ]
        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "glm_second_level")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        design_matrix_payload = params.get("design_matrix")
        if isinstance(design_matrix_payload, str):
            design_matrix_path = Path(design_matrix_payload).expanduser().resolve()
            sep = "\\t" if design_matrix_path.suffix.lower() == ".tsv" else ","
            design_matrix = pd.read_csv(design_matrix_path, sep=sep)
        elif isinstance(design_matrix_payload, dict):
            design_matrix = pd.DataFrame(design_matrix_payload)
        else:
            design_matrix = pd.DataFrame({"intercept": np.ones(len(contrast_maps))})

        model_kwargs = {
            "mask_img": params.get("mask_img"),
            "smoothing_fwhm": params.get("smoothing_fwhm"),
        }
        model_type = str(params.get("model_type", "ols"))
        try:
            model = SecondLevelModel(
                model_type=model_type,
                **model_kwargs,
            ).fit(contrast_maps, design_matrix=design_matrix)
        except TypeError:
            model = SecondLevelModel(**model_kwargs).fit(
                contrast_maps,
                design_matrix=design_matrix,
            )

        contrast = params.get("contrast") or "intercept"
        z_map = model.compute_contrast(contrast, output_type="z_score")
        zmap_path = output_dir / "group_zmap.nii.gz"
        z_map.to_filename(zmap_path)

        summary = {
            "model_type": model_type,
            "n_maps": len(contrast_maps),
            "design_columns": list(design_matrix.columns),
            "used_nilearn_package": True,
        }
        summary_path = output_dir / "glm_second_level_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        print(
            json.dumps(
                {
                    "outputs": {
                        "summary": str(summary_path),
                        "zmap": str(zmap_path),
                    },
                    "summary": summary,
                    "message": "Second-level GLM completed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """
    ).lstrip()


def _connectivity_matrix_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np
        from nilearn.connectome import ConnectivityMeasure

        from brain_researcher.core.analysis.connectivity_contracts import (
            build_feature_contract,
            safe_fisher_z,
            write_feature_contract,
        )


        def _load_timeseries(value):
            if isinstance(value, str):
                path = Path(value).expanduser().resolve()
                suffix = path.suffix.lower()
                if suffix in {".npy", ".npz"}:
                    data = np.load(path)
                elif suffix in {".csv", ".tsv", ".txt"}:
                    delimiter = "," if suffix == ".csv" else "\\t"
                    data = np.loadtxt(path, delimiter=delimiter)
                else:
                    data = np.load(path)
            elif isinstance(value, list) and value and isinstance(value[0], str):
                loaded = []
                for item in value:
                    path = Path(item).expanduser().resolve()
                    suffix = path.suffix.lower()
                    if suffix in {".npy", ".npz"}:
                        loaded.append(np.load(path))
                    elif suffix in {".csv", ".tsv", ".txt"}:
                        delimiter = "," if suffix == ".csv" else "\\t"
                        loaded.append(np.loadtxt(path, delimiter=delimiter))
                    else:
                        loaded.append(np.load(path))
                data = np.asarray(loaded)
            else:
                data = np.asarray(value, dtype=float)

            if data.ndim == 1:
                raise ValueError("timeseries input must be at least 2D (time x roi)")
            if data.ndim == 2:
                data = data[np.newaxis, ...]
            if data.ndim != 3:
                raise ValueError(
                    f"timeseries array must be 3D (subjects x time x roi), got {data.ndim}"
                )
            return np.asarray(data, dtype=float)


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        timeseries = _load_timeseries(params["timeseries"])
        measure = ConnectivityMeasure(
            kind=str(params.get("kind", "correlation")),
            vectorize=bool(params.get("vectorize", False)),
            discard_diagonal=bool(params.get("discard_diagonal", False)),
            standardize="zscore_sample",
        )
        matrix = measure.fit_transform([timeseries[idx] for idx in range(timeseries.shape[0])])
        fisher_z_diagnostics = None
        if bool(params.get("fisher_z", True)):
            matrix, fisher_z_diagnostics = safe_fisher_z(
                matrix,
                f"connectivity_matrix(kind={params.get('kind', 'correlation')})",
                return_diagnostics=True,
            )

        output_file = Path(
            params.get("output_file") or (Path.cwd() / "connectivity_matrix.npy")
        ).expanduser().resolve()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_file, matrix)

        summary = {
            "kind": str(params.get("kind", "correlation")),
            "shape": list(matrix.shape),
            "n_subjects": int(timeseries.shape[0]),
            "n_rois": int(timeseries.shape[-1]),
            "used_nilearn_package": True,
            "fisher_z_applied": bool(params.get("fisher_z", True)),
        }
        if fisher_z_diagnostics is not None:
            summary["fisher_z_diagnostics"] = fisher_z_diagnostics
        outputs = {
            "matrix": str(output_file),
            "connectivity_matrix": str(output_file),
        }
        try:
            cov_estimator_obj = getattr(measure, "cov_estimator_", None) or getattr(
                measure, "cov_estimator", None
            )
            cov_estimator_name = (
                type(cov_estimator_obj).__name__
                if cov_estimator_obj is not None
                else None
            )
            contract = build_feature_contract(
                matrix,
                matrix_kind=str(params.get("kind", "correlation")),
                source_level="roi_timeseries",
                n_rois=int(timeseries.shape[-1]),
                n_timepoints=int(timeseries.shape[1]),
                effective_n_timepoints=int(timeseries.shape[1]),
                covariance_estimator=cov_estimator_name,
                fisher_z_diagnostics=fisher_z_diagnostics,
                extras={
                    "n_subjects": int(timeseries.shape[0]),
                    "vectorize": bool(params.get("vectorize", False)),
                    "discard_diagonal": bool(params.get("discard_diagonal", False)),
                },
            )
            outputs["feature_contract"] = str(
                write_feature_contract(contract, output_file.parent)
            )
        except Exception as exc:
            summary["feature_contract_warning"] = (
                f"feature_contract sidecar emission failed: {exc!r}"
            )
        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "message": "Connectivity matrix computed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """
    ).lstrip()


def _seed_based_connectivity_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np
        import pandas as pd
        from nilearn.maskers import NiftiMasker, NiftiSpheresMasker


        def _zscore(values, axis):
            mean = values.mean(axis=axis, keepdims=True)
            std = values.std(axis=axis, keepdims=True)
            std[std < 1e-6] = 1e-6
            return (values - mean) / std


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        img_path = Path(params["img"]).expanduser().resolve()
        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "seed_based_fc")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        confounds = None
        confounds_path = params.get("confounds")
        if confounds_path:
            confounds_file = Path(confounds_path).expanduser().resolve()
            sep = "\\t" if confounds_file.suffix.lower() == ".tsv" else ","
            confounds = (
                pd.read_csv(confounds_file, sep=sep)
                .select_dtypes(include=[np.number])
                .fillna(0.0)
                .to_numpy()
            )
            confound_mean = confounds.mean(axis=0, keepdims=True)
            confound_std = confounds.std(axis=0, ddof=1, keepdims=True)
            confound_std[~np.isfinite(confound_std) | (confound_std < 1e-6)] = 1.0
            confounds = (confounds - confound_mean) / confound_std

        brain_masker = NiftiMasker(
            mask_img=params.get("mask_img"),
            smoothing_fwhm=params.get("smoothing_fwhm"),
            standardize=(
                "zscore_sample" if bool(params.get("standardize", True)) else False
            ),
            standardize_confounds=False,
            detrend=bool(params.get("detrend", True)),
            low_pass=params.get("low_pass"),
            high_pass=params.get("high_pass"),
            t_r=params.get("t_r"),
        )
        brain_ts = brain_masker.fit_transform(str(img_path), confounds=confounds)

        seed_mask = params.get("seed_mask")
        if seed_mask:
            seed_masker = NiftiMasker(
                mask_img=str(Path(seed_mask).expanduser().resolve()),
                standardize=(
                    "zscore_sample" if bool(params.get("standardize", True)) else False
                ),
                standardize_confounds=False,
                detrend=bool(params.get("detrend", True)),
                low_pass=params.get("low_pass"),
                high_pass=params.get("high_pass"),
                t_r=params.get("t_r"),
            )
            seed_ts = seed_masker.fit_transform(str(img_path), confounds=confounds)
            seed_descriptor = seed_mask
        else:
            seed_coords = params.get("seed_coords")
            if not seed_coords:
                raise ValueError("seed_coords or seed_mask is required")
            seed_masker = NiftiSpheresMasker(
                [tuple(seed_coords)],
                radius=float(params.get("radius", 8.0)),
                standardize=(
                    "zscore_sample" if bool(params.get("standardize", True)) else False
                ),
                standardize_confounds=False,
                detrend=bool(params.get("detrend", True)),
                low_pass=params.get("low_pass"),
                high_pass=params.get("high_pass"),
                t_r=params.get("t_r"),
            )
            seed_ts = seed_masker.fit_transform(str(img_path), confounds=confounds)
            seed_descriptor = seed_coords

        seed_ts = _zscore(seed_ts.mean(axis=1, keepdims=True), axis=0)
        brain_ts = _zscore(brain_ts, axis=0)
        corr = (brain_ts * seed_ts).mean(axis=0)
        seed_map = brain_masker.inverse_transform(corr)

        output_file = Path(
            params.get("output_file")
            or (output_dir / "seed_based_connectivity.nii.gz")
        ).expanduser().resolve()
        output_file.parent.mkdir(parents=True, exist_ok=True)
        seed_map.to_filename(output_file)

        summary = {
            "radius": float(params.get("radius", 8.0)),
            "seed": seed_descriptor,
            "n_voxels": int(corr.size),
            "used_nilearn_package": True,
        }
        print(
            json.dumps(
                {
                    "outputs": {"map": str(output_file)},
                    "summary": summary,
                    "message": "Seed-based connectivity completed.",
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        """
    ).lstrip()


def _mvpa_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np
        from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        from sklearn.feature_selection import SelectKBest, f_classif
        from sklearn.linear_model import LogisticRegression, RidgeClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.naive_bayes import GaussianNB
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import LinearSVC


        def _load_labels(value):
            if isinstance(value, str):
                path = Path(value).expanduser().resolve()
                if path.suffix.lower() == ".npy":
                    labels = np.load(path)
                else:
                    delimiter = "," if path.suffix.lower() == ".csv" else None
                    labels = np.loadtxt(path, delimiter=delimiter)
                return np.asarray(labels).ravel()
            return np.asarray(value).ravel()


        def _load_data(path_text, *, mask_img=None, standardize=False, smoothing_fwhm=None):
            path = Path(path_text).expanduser().resolve()
            lower_name = path.name.lower()
            if lower_name.endswith(".nii") or lower_name.endswith(".nii.gz"):
                from nilearn.maskers import NiftiMasker

                masker = NiftiMasker(
                    mask_img=(
                        str(Path(mask_img).expanduser().resolve()) if mask_img else None
                    ),
                    standardize=standardize,
                    smoothing_fwhm=smoothing_fwhm,
                )
                data = masker.fit_transform(str(path))
            elif path.suffix.lower() == ".npy":
                data = np.load(path)
            else:
                delimiter = "," if path.suffix.lower() == ".csv" else None
                data = np.loadtxt(path, delimiter=delimiter)
            if data.ndim == 1:
                data = data[:, np.newaxis]
            return np.asarray(data, dtype=float)


        def _build_classifier(name, seed):
            lowered = str(name or "svc").lower()
            if lowered in {"lda", "linear_discriminant_analysis"}:
                return LinearDiscriminantAnalysis()
            if lowered in {"gnb", "gaussiannb"}:
                return GaussianNB()
            if lowered in {"ridge", "ridge_classifier"}:
                return RidgeClassifier()
            if lowered in {"logistic", "logreg", "logistic_regression"}:
                return LogisticRegression(
                    max_iter=1000,
                    random_state=seed,
                    solver="liblinear",
                )
            return LinearSVC(random_state=seed, dual="auto")


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        data = _load_data(
            params["img"],
            mask_img=params.get("mask_img"),
            standardize=False,
            smoothing_fwhm=params.get("smoothing_fwhm"),
        )
        labels = _load_labels(params["labels"])
        if len(labels) != data.shape[0]:
            raise ValueError("labels length must match number of samples in img")

        steps = []
        if bool(params.get("standardize", True)):
            steps.append(("scale", StandardScaler()))
        k_features = params.get("n_features")
        if params.get("feature_selection") and k_features:
            steps.append(
                ("select", SelectKBest(score_func=f_classif, k=min(int(k_features), data.shape[1])))
            )
        steps.append(
            (
                "classifier",
                _build_classifier(params.get("classifier", "svc"), params.get("seed")),
            )
        )
        pipeline = Pipeline(steps)

        cv_folds = int(params.get("cv_folds", 5))
        splitter = StratifiedKFold(
            n_splits=max(2, min(cv_folds, len(labels))),
            shuffle=True,
            random_state=params.get("seed"),
        )
        scores = cross_val_score(pipeline, data, labels, cv=splitter, scoring="accuracy")

        pvalue = None
        permutations = int(params.get("permutations", 0))
        if permutations > 0:
            rng = np.random.default_rng(params.get("seed"))
            null_scores = []
            for _ in range(permutations):
                shuffled = rng.permutation(labels)
                null_scores.append(
                    float(
                        np.mean(
                            cross_val_score(
                                pipeline,
                                data,
                                shuffled,
                                cv=splitter,
                                scoring="accuracy",
                            )
                        )
                    )
                )
            pvalue = float(
                (np.sum(np.asarray(null_scores) >= float(scores.mean())) + 1)
                / (len(null_scores) + 1)
            )

        summary = {
            "classifier": str(params.get("classifier", "svc")),
            "accuracy": float(scores.mean()),
            "std": float(scores.std(ddof=0)),
            "folds": int(len(scores)),
            "used_sklearn": True,
        }
        outputs = {"summary": None, "scores": None}
        output_dir = params.get("output_dir")
        if output_dir:
            out_dir = Path(output_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            scores_path = out_dir / "mvpa_scores.npy"
            np.save(scores_path, scores)
            outputs["scores"] = str(scores_path)
            summary_path = out_dir / "mvpa_summary.json"
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            outputs["summary"] = str(summary_path)

        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "scores": scores.tolist(),
                    "pvalue": pvalue,
                    "message": "MVPA decoding completed.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """
    ).lstrip()


def _temporal_decoding_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np


        def _load_array(path_text):
            path = Path(path_text).expanduser().resolve()
            if path.suffix.lower() == ".npy":
                return np.load(path)
            if path.suffix.lower() == ".npz":
                archive = np.load(path)
                return archive[archive.files[0]]
            raise ValueError(f"unsupported array format: {path_text}")


        def _standardize(values):
            mean = np.mean(values, axis=0, keepdims=True)
            std = np.std(values, axis=0, keepdims=True) + 1e-6
            return (values - mean) / std


        def _generate_windows(length, window_size, step):
            windows = []
            for start in range(0, length - window_size + 1, step):
                windows.append((start, start + window_size))
            return windows or [(0, length)]


        def _compute_cv_folds(labels, requested_folds):
            _, counts = np.unique(labels, return_counts=True)
            if counts.size < 2:
                return 0
            max_folds = int(min(max(2, requested_folds), np.min(counts)))
            return max_folds if max_folds >= 2 else 0


        def _nearest_centroid_predict(train_x, train_y, test_x):
            classes = np.unique(train_y)
            centroids = np.vstack([train_x[train_y == cls].mean(axis=0) for cls in classes])
            dists = np.sum((test_x[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
            return classes[np.argmin(dists, axis=1)]


        def _deterministic_stratified_folds(labels, n_splits):
            folds = [[] for _ in range(n_splits)]
            for cls in np.unique(labels):
                cls_idx = np.where(labels == cls)[0]
                for index, row_id in enumerate(cls_idx):
                    folds[index % n_splits].append(int(row_id))
            return [np.asarray(sorted(fold), dtype=int) for fold in folds if fold]


        def _nearest_centroid_cv_accuracy(data, labels, n_splits):
            all_idx = np.arange(labels.size)
            fold_accuracies = []
            for test_idx in _deterministic_stratified_folds(labels, n_splits):
                train_idx = np.setdiff1d(all_idx, test_idx)
                train_labels = labels[train_idx]
                if np.unique(train_labels).size < 2:
                    continue
                predictions = _nearest_centroid_predict(
                    data[train_idx],
                    train_labels,
                    data[test_idx],
                )
                fold_accuracies.append(float(np.mean(predictions == labels[test_idx])))
            if not fold_accuracies:
                _, counts = np.unique(labels, return_counts=True)
                return float(np.max(counts) / labels.size)
            return float(np.mean(fold_accuracies))


        def _run_sklearn_cv(data, labels, classifier_name, n_splits, random_state):
            from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
            from sklearn.linear_model import LogisticRegression, RidgeClassifier
            from sklearn.model_selection import StratifiedKFold, cross_val_score
            from sklearn.svm import LinearSVC

            lowered = str(classifier_name or "lda").lower()
            if lowered == "lda":
                classifier = LinearDiscriminantAnalysis()
            elif lowered in {"svm", "svc", "linearsvc"}:
                classifier = LinearSVC(random_state=random_state)
            elif lowered in {"ridge", "ridge_classifier"}:
                classifier = RidgeClassifier()
            else:
                classifier = LogisticRegression(
                    max_iter=1000,
                    random_state=random_state,
                    solver="liblinear",
                )

            cv = StratifiedKFold(
                n_splits=n_splits,
                shuffle=True,
                random_state=0 if random_state is None else int(random_state),
            )
            scores = cross_val_score(classifier, data, labels, cv=cv, scoring="accuracy")
            return float(np.mean(scores)), "sklearn_cv"


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        data = _load_array(params["data_file"])
        labels = np.asarray(_load_array(params["labels_file"])).astype(int).reshape(-1)

        if data.ndim == 3:
            timepoints = data.shape[0]
            timeseries = np.transpose(data, (2, 0, 1))
        elif data.ndim == 2:
            if labels.size == data.shape[0] and labels.size >= 2:
                timepoints = 1
                timeseries = data[:, np.newaxis, :]
            else:
                timepoints = data.shape[0]
                timeseries = data[np.newaxis, ...]
        else:
            raise ValueError("data must be 2D or 3D")

        n_trials = timeseries.shape[0]
        if labels.size < n_trials:
            raise ValueError("labels must contain at least one label per trial")
        labels = labels[:n_trials]

        window_size = int(params.get("window_size") or max(1, timepoints // 10))
        window_step = int(params.get("window_step", 1))
        windows = _generate_windows(timepoints, window_size, window_step)

        accuracies = []
        patterns = []
        backend_names = []
        backend_reasons = []
        for start, end in windows:
            window_data = timeseries[:, start:end, :].reshape(n_trials, -1)
            window_data = _standardize(window_data)
            n_splits = _compute_cv_folds(labels, int(params.get("cv_folds", 5)))
            if labels.size < 2 or np.unique(labels).size < 2:
                accuracy = 0.0
                backend_name = "insufficient_labels"
                backend_reason = "single_class_or_not_enough_trials"
            elif n_splits < 2:
                _, counts = np.unique(labels, return_counts=True)
                accuracy = float(np.max(counts) / labels.size)
                backend_name = "insufficient_cv_folds"
                backend_reason = "class_counts_too_small_for_cv"
            else:
                try:
                    accuracy, backend_name = _run_sklearn_cv(
                        window_data,
                        labels,
                        params.get("classifier", "lda"),
                        n_splits,
                        params.get("random_state"),
                    )
                    backend_reason = "ok"
                except Exception:
                    accuracy = _nearest_centroid_cv_accuracy(window_data, labels, n_splits)
                    backend_name = "numpy_nearest_centroid_cv"
                    backend_reason = "sklearn_failed_or_unavailable"
            accuracies.append(float(accuracy))
            backend_names.append(backend_name)
            backend_reasons.append(backend_reason)
            patterns.append(window_data.mean(axis=0))

        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "temporal_decoding")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        mean_accuracy = float(np.mean(accuracies))
        std_accuracy = float(np.std(accuracies))
        summary = {
            "method": str(params.get("method", "sliding_window")),
            "classifier": str(params.get("classifier", "lda")),
            "n_trials": int(n_trials),
            "window_size": int(window_size),
            "n_windows": int(len(windows)),
            "mean_accuracy": mean_accuracy,
            "std_accuracy": std_accuracy,
            "n_classes": int(np.unique(labels).size),
            "effective_cv_folds": int(_compute_cv_folds(labels, int(params.get("cv_folds", 5)))),
            "used_full_backend": any(name == "sklearn_cv" for name in backend_names),
            "backend_name": (
                backend_names[0] if len(set(backend_names)) == 1 else "mixed_backends"
            ),
            "backend_reason": (
                backend_reasons[0]
                if len(set(backend_reasons)) == 1
                else "mixed_reasons"
            ),
        }

        outputs = {"summary": None, "accuracies": None, "patterns": None}
        summary_path = output_dir / "temporal_decoding_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        outputs["summary"] = str(summary_path)

        if bool(params.get("save_accuracies", True)):
            acc_path = output_dir / "temporal_accuracies.npy"
            np.save(acc_path, np.asarray(accuracies))
            outputs["accuracies"] = str(acc_path)

        if bool(params.get("save_patterns", True)):
            patterns_path = output_dir / "temporal_patterns.npy"
            np.save(patterns_path, np.asarray(patterns))
            outputs["patterns"] = str(patterns_path)

        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "accuracies": accuracies,
                    "message": f"Temporal decoding completed ({summary['backend_name']}).",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """
    ).lstrip()


def _encoding_models_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np


        def _load_array(path_text):
            path = Path(path_text).expanduser().resolve()
            if path.suffix.lower() == ".npy":
                return np.load(path)
            if path.suffix.lower() == ".npz":
                archive = np.load(path)
                return archive[archive.files[0]]
            raise ValueError(f"unsupported array format: {path_text}")


        def _prepare_design_matrix(stimulus, add_derivatives):
            design = stimulus
            if add_derivatives:
                first_derivative = np.diff(stimulus, axis=0, prepend=stimulus[0:1])
                design = np.concatenate([design, first_derivative], axis=1)
            return design


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        brain_data = _load_array(params["brain_data_file"])
        stimulus = _load_array(params["stimulus_file"])
        if brain_data.shape[0] != stimulus.shape[0]:
            raise ValueError("brain data and stimulus must share the same time dimension")

        design = _prepare_design_matrix(stimulus, bool(params.get("add_derivatives", False)))
        if bool(params.get("standardize", True)):
            design = (design - np.mean(design, axis=0)) / (np.std(design, axis=0) + 1e-6)

        alpha = 1.0
        xtx = design.T @ design
        ridge_matrix = xtx + alpha * np.eye(xtx.shape[0])
        xty = design.T @ brain_data
        try:
            weights = np.linalg.solve(ridge_matrix, xty)
            used_full_backend = bool(np.all(np.isfinite(weights)))
            backend_name = "numpy_solve"
        except np.linalg.LinAlgError:
            weights = np.linalg.pinv(ridge_matrix) @ xty
            used_full_backend = False
            backend_name = "numpy_fallback"

        predicted = design @ weights
        residuals = brain_data - predicted
        denom = np.sum(
            (brain_data - np.mean(brain_data, axis=0)) ** 2,
            axis=0,
        ) + 1e-8
        r2_scores = 1.0 - np.sum(residuals ** 2, axis=0) / denom
        r2_scores = np.clip(r2_scores, -1.0, 1.0)

        output_dir = Path(
            params.get("output_dir") or (Path.cwd() / "encoding_models")
        ).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        outputs = {"summary": None, "weights": None, "predictions": None, "model": None}
        if bool(params.get("save_weights", True)):
            weights_path = output_dir / "encoding_weights.npy"
            np.save(weights_path, weights)
            outputs["weights"] = str(weights_path)
        if bool(params.get("save_predictions", True)):
            predictions_path = output_dir / "encoding_predictions.npy"
            np.save(predictions_path, predicted)
            outputs["predictions"] = str(predictions_path)

        summary = {
            "model_type": str(params.get("model_type", "ridge")).lower(),
            "n_timepoints": int(brain_data.shape[0]),
            "n_voxels": int(brain_data.shape[1]),
            "n_features": int(design.shape[1]),
            "mean_r2": float(np.mean(r2_scores)),
            "median_r2": float(np.median(r2_scores)),
            "used_full_backend": used_full_backend,
            "backend_name": backend_name,
        }
        summary_path = output_dir / "encoding_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        outputs["summary"] = str(summary_path)

        if bool(params.get("save_models", True)):
            model_path = output_dir / "encoding_model.json"
            model_path.write_text(
                json.dumps({"alpha": alpha, "type": summary["model_type"]}),
                encoding="utf-8",
            )
            outputs["model"] = str(model_path)

        print(
            json.dumps(
                {
                    "outputs": outputs,
                    "summary": summary,
                    "r2_scores": r2_scores.tolist(),
                    "message": f"Encoding model completed ({backend_name}).",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """
    ).lstrip()


def _searchlight_python_script() -> str:
    return dedent(
        """
        import json
        from pathlib import Path

        import numpy as np
        from nilearn import image
        from nilearn.searchlight import SearchLight


        def _load_labels(params):
            labels = params.get("labels")
            if labels is not None:
                return np.asarray(labels)
            labels_file = params.get("labels_file")
            if labels_file:
                return np.loadtxt(Path(labels_file).expanduser().resolve())
            raise ValueError("labels or labels_file is required for searchlight analysis")


        def _get_classifier(name, analysis_type):
            from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
            from sklearn.linear_model import LogisticRegression, Ridge, RidgeClassifier
            from sklearn.naive_bayes import GaussianNB
            from sklearn.svm import SVC, SVR

            lowered = str(name or "svm").lower()
            if analysis_type == "regression":
                if lowered == "svr":
                    return SVR(kernel="linear", C=1.0)
                return Ridge()
            classifiers = {
                "svm": SVC(kernel="linear", C=1.0),
                "svc": SVC(kernel="linear", C=1.0),
                "lda": LinearDiscriminantAnalysis(),
                "gnb": GaussianNB(),
                "ridge": RidgeClassifier(),
                "logistic": LogisticRegression(max_iter=1000),
            }
            return classifiers.get(lowered, SVC(kernel="linear", C=1.0))


        def _searchlight_classification(func_img, labels, radius, classifier_name, cv_folds, n_jobs, mask_img):
            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=_get_classifier(classifier_name, "classification"),
                cv=cv_folds,
                scoring="accuracy",
            )
            searchlight.fit(func_img, labels)
            return searchlight.scores_img_


        def _searchlight_regression(func_img, targets, radius, regressor_name, cv_folds, n_jobs, mask_img):
            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=_get_classifier(regressor_name, "regression"),
                cv=cv_folds,
                scoring="r2",
            )
            searchlight.fit(func_img, targets)
            return searchlight.scores_img_


        def _searchlight_rsa(func_img, model_rdm, radius, n_jobs, mask_img):
            from scipy.stats import spearmanr
            from sklearn.base import BaseEstimator


            class RSAEstimator(BaseEstimator):
                def __init__(self, model_rdm):
                    self.model_rdm = model_rdm

                def fit(self, X, y=None):
                    data_rdm = 1 - np.corrcoef(X)
                    upper = np.triu_indices(data_rdm.shape[0], k=1)
                    corr, _ = spearmanr(data_rdm[upper], self.model_rdm[upper])
                    self.score_ = 0.0 if np.isnan(corr) else float(corr)
                    return self

                def score(self, X, y=None):
                    return self.score_


            searchlight = SearchLight(
                mask_img=mask_img,
                radius=radius,
                n_jobs=n_jobs,
                verbose=0,
                estimator=RSAEstimator(model_rdm),
            )
            searchlight.fit(func_img)
            return searchlight.scores_img_


        def _permutation_searchlight(func_img, labels, radius, classifier_name, cv_folds, n_permutations, n_jobs, mask_img):
            observed_img = _searchlight_classification(
                func_img,
                labels,
                radius,
                classifier_name,
                cv_folds,
                n_jobs,
                mask_img,
            )
            perm_scores = []
            rng = np.random.default_rng(0)
            for _ in range(n_permutations):
                perm_img = _searchlight_classification(
                    func_img,
                    rng.permutation(labels),
                    radius,
                    classifier_name,
                    cv_folds,
                    n_jobs,
                    mask_img,
                )
                perm_scores.append(perm_img.get_fdata())
            p_values = np.mean(
                np.asarray(perm_scores) >= observed_img.get_fdata()[np.newaxis, ...],
                axis=0,
            )
            return observed_img, image.new_img_like(observed_img, p_values)


        def _plot(scores_img, output_file, threshold, title):
            from nilearn import plotting
            import matplotlib.pyplot as plt

            figure = plt.figure(figsize=(12, 8))
            plotting.plot_glass_brain(
                scores_img,
                threshold=threshold,
                colorbar=True,
                title=title,
                figure=figure,
            )
            plt.savefig(output_file, dpi=150, bbox_inches="tight")
            plt.close()


        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        func_img = image.load_img(str(Path(params["func_file"]).expanduser().resolve()))
        mask_file = params.get("mask_file")
        mask_img = image.load_img(str(Path(mask_file).expanduser().resolve())) if mask_file else None
        labels = _load_labels(params)
        output_dir = Path(params["output_dir"]).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        analysis_type = str(params.get("analysis_type", "classification"))
        radius = float(params.get("radius", 6.0))
        classifier = str(params.get("classifier", "svm"))
        cv_folds = int(params.get("cv_folds", 5))
        n_jobs = int(params.get("n_jobs", 1))
        n_permutations = int(params.get("n_permutations", 0))

        if analysis_type == "classification":
            if n_permutations > 0:
                scores_img, p_value_img = _permutation_searchlight(
                    func_img,
                    labels,
                    radius,
                    classifier,
                    cv_folds,
                    n_permutations,
                    n_jobs,
                    mask_img,
                )
            else:
                scores_img = _searchlight_classification(
                    func_img,
                    labels,
                    radius,
                    classifier,
                    cv_folds,
                    n_jobs,
                    mask_img,
                )
                p_value_img = None
        elif analysis_type == "regression":
            scores_img = _searchlight_regression(
                func_img,
                labels,
                radius,
                classifier,
                cv_folds,
                n_jobs,
                mask_img,
            )
            p_value_img = None
        elif analysis_type == "rsa":
            model_rdm_file = params.get("model_rdm_file")
            if not model_rdm_file:
                raise ValueError("model_rdm_file is required for RSA searchlight")
            model_rdm = np.load(Path(model_rdm_file).expanduser().resolve())
            scores_img = _searchlight_rsa(
                func_img,
                model_rdm,
                radius,
                n_jobs,
                mask_img,
            )
            p_value_img = None
        else:
            raise ValueError(f"unknown analysis_type: {analysis_type}")

        output_files = {}
        if bool(params.get("save_maps", True)):
            scores_file = output_dir / f"searchlight_{analysis_type}_scores.nii.gz"
            scores_img.to_filename(scores_file)
            output_files["scores_map"] = str(scores_file)
            if p_value_img is not None:
                p_file = output_dir / f"searchlight_{analysis_type}_pvalues.nii.gz"
                p_value_img.to_filename(p_file)
                output_files["p_value_map"] = str(p_file)

        scores_data = scores_img.get_fdata()
        valid_scores = scores_data[~np.isnan(scores_data) & (scores_data != 0)]
        stats = {
            "mean_score": float(np.mean(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "std_score": float(np.std(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "max_score": float(np.max(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "min_score": float(np.min(valid_scores)) if len(valid_scores) > 0 else 0.0,
            "n_voxels_analyzed": int(len(valid_scores)),
            "parameters": {
                "radius": radius,
                "analysis_type": analysis_type,
                "classifier": classifier if analysis_type == "classification" else None,
                "cv_folds": cv_folds,
                "n_permutations": n_permutations,
            },
        }

        if bool(params.get("plot_results", True)):
            threshold = params.get("threshold")
            plot_file = output_dir / f"searchlight_{analysis_type}_plot.png"
            _plot(scores_img, str(plot_file), threshold, f"Searchlight {analysis_type.title()} Results")
            output_files["plot"] = str(plot_file)
            if p_value_img is not None:
                p_plot_file = output_dir / f"searchlight_{analysis_type}_pvalue_plot.png"
                _plot(p_value_img, str(p_plot_file), 0.05, "Searchlight P-values")
                output_files["p_value_plot"] = str(p_plot_file)

        if bool(params.get("save_stats", True)):
            stats_file = output_dir / f"searchlight_{analysis_type}_stats.json"
            stats_file.write_text(json.dumps(stats, indent=2), encoding="utf-8")
            output_files["stats"] = str(stats_file)

        print(
            json.dumps(
                {
                    "outputs": output_files,
                    "statistics": stats,
                    "message": f"Searchlight {analysis_type} completed: mean score = {stats['mean_score']:.3f}",
                },
                indent=2,
                sort_keys=True,
            )
        )
        """
    ).lstrip()


def _direct_python_script_for_family(tool_id: str, recipe_family: str) -> str:
    if recipe_family == "glm":
        return (
            _glm_first_level_python_script()
            if tool_id == "glm_first_level"
            else _glm_second_level_python_script()
        )
    if recipe_family == "connectivity_matrix":
        return _connectivity_matrix_python_script()
    if recipe_family == "seed_based_connectivity":
        return _seed_based_connectivity_python_script()
    if recipe_family == "mvpa":
        return _mvpa_python_script()
    if recipe_family == "temporal_decoding":
        return _temporal_decoding_python_script()
    if recipe_family == "encoding_models":
        return _encoding_models_python_script()
    if recipe_family == "searchlight":
        return _searchlight_python_script()
    raise ValueError(f"Unsupported direct python recipe family: {recipe_family}")


def _rest_connectome_python_script() -> str:
    return (
        "import json\n"
        "import importlib\n"
        "import os\n"
        "import re\n"
        "import shutil\n"
        "from pathlib import Path\n\n"
        "import nibabel as nib\n"
        "import numpy as np\n"
        "from brain_researcher.core.analysis.connectivity_contracts import build_feature_contract, safe_fisher_z, write_feature_contract\n"
        "from nilearn import datasets\n"
        "from nilearn.connectome import ConnectivityMeasure\n"
        "from nilearn.maskers import NiftiLabelsMasker\n\n"
        "def _parse_schaefer_rois(name: str) -> int:\n"
        '    match = re.search(r"(\\d+)", name)\n'
        "    return int(match.group(1)) if match else 200\n\n"
        "def _parse_schaefer_networks(name: str) -> int:\n"
        "    lowered = name.lower()\n"
        "    if '17network' in lowered or '_17' in lowered:\n"
        "        return 17\n"
        "    return 7\n\n"
        "def _bids_entities(path: Path) -> dict[str, str]:\n"
        "    name = path.name\n"
        "    stem = name[:-7] if name.endswith('.nii.gz') else path.stem\n"
        "    entities = {}\n"
        "    for match in re.finditer(r'(?:^|_)([A-Za-z0-9]+)-([^_]+)', stem):\n"
        "        entities[match.group(1)] = match.group(2)\n"
        "    return entities\n\n"
        "def _normalize_res(value: str | int | None) -> str | None:\n"
        "    if value is None:\n"
        "        return None\n"
        "    text = str(value).strip().lower()\n"
        "    if not text:\n"
        "        return None\n"
        "    if text.endswith('mm'):\n"
        "        text = text[:-2]\n"
        "    if text.isdigit():\n"
        "        text = str(int(text))\n"
        "    return text or None\n\n"
        "def _template_candidates(space: str | None) -> list[str]:\n"
        "    explicit = (space or '').strip()\n"
        "    if explicit.startswith('tpl-'):\n"
        "        explicit = explicit[4:]\n"
        "    defaults = ['MNI152NLin2009cAsym', 'MNI152NLin6Asym', 'MNI152Lin']\n"
        "    alias_map = {\n"
        "        'MNI152': defaults,\n"
        "        'FSLMNI152': ['MNI152NLin6Asym', 'MNI152Lin'],\n"
        "    }\n"
        "    candidates = []\n"
        "    if explicit:\n"
        "        candidates.extend(alias_map.get(explicit, [explicit]))\n"
        "    candidates.extend(defaults)\n"
        "    ordered = []\n"
        "    seen = set()\n"
        "    for candidate in candidates:\n"
        "        if not candidate or candidate in seen:\n"
        "            continue\n"
        "        seen.add(candidate)\n"
        "        ordered.append(candidate)\n"
        "    return ordered\n\n"
        "def _find_local_templateflow_schaefer(atlas_name: str, img_path: Path) -> Path | None:\n"
        "    roots = []\n"
        "    tf_home = os.getenv('TEMPLATEFLOW_HOME', '').strip()\n"
        "    if tf_home:\n"
        "        root = Path(tf_home).expanduser().resolve()\n"
        "        if root.exists() and root.is_dir():\n"
        "            roots.append(root)\n"
        "    for item in [entry.strip() for entry in os.getenv('BR_ATLAS_SEARCH_ROOTS', '').split(',') if entry.strip()]:\n"
        "        root = Path(item).expanduser().resolve()\n"
        "        if root.exists() and root.is_dir():\n"
        "            roots.append(root)\n"
        "    if not roots:\n"
        "        return None\n"
        "    ref_entities = _bids_entities(img_path)\n"
        "    wanted_space = ref_entities.get('space') or ref_entities.get('tpl')\n"
        "    wanted_res = _normalize_res(ref_entities.get('res'))\n"
        "    n_rois = _parse_schaefer_rois(atlas_name)\n"
        "    n_networks = _parse_schaefer_networks(atlas_name)\n"
        "    candidates = []\n"
        "    seen = set()\n"
        "    for root in roots:\n"
        "        for path in sorted(root.rglob('*.nii*')):\n"
        "            key = str(path)\n"
        "            if key in seen:\n"
        "                continue\n"
        "            seen.add(key)\n"
        "            name = path.name\n"
        "            if 'atlas-Schaefer2018' not in name or 'dseg' not in name:\n"
        "                continue\n"
        "            desc_match = re.search(r'desc-(\\d+)Parcels(\\d+)Networks', name)\n"
        "            if desc_match is None:\n"
        "                continue\n"
        "            if int(desc_match.group(1)) != n_rois or int(desc_match.group(2)) != n_networks:\n"
        "                continue\n"
        "            entities = _bids_entities(path)\n"
        "            score = (\n"
        "                int(not wanted_space or entities.get('tpl') == wanted_space),\n"
        "                int(wanted_res is None or _normalize_res(entities.get('res')) == wanted_res),\n"
        "                str(path),\n"
        "            )\n"
        "            candidates.append((score, path))\n"
        "    if candidates:\n"
        "        candidates.sort(key=lambda item: item[0])\n"
        "        return candidates[-1][1]\n"
        "    try:\n"
        "        templateflow_api = importlib.import_module('templateflow.api')\n"
        "    except ImportError:\n"
        "        return None\n"
        "    for template in _template_candidates(wanted_space):\n"
        "        query_resolutions = [int(wanted_res)] if wanted_res and wanted_res.isdigit() else []\n"
        "        query_resolutions.append(None)\n"
        "        for query_resolution in query_resolutions:\n"
        "            query = {\n"
        "                'atlas': 'Schaefer2018',\n"
        "                'desc': f'{n_rois}Parcels{n_networks}Networks',\n"
        "                'suffix': 'dseg',\n"
        "                'extension': ['.nii.gz', '.nii'],\n"
        "            }\n"
        "            if query_resolution is not None:\n"
        "                query['resolution'] = query_resolution\n"
        "            try:\n"
        "                fetched = templateflow_api.get(template, raise_empty=True, **query)\n"
        "            except Exception:\n"
        "                continue\n"
        "            fetched_paths = [Path(fetched)] if isinstance(fetched, (str, os.PathLike)) else [Path(p) for p in fetched]\n"
        "            for path in fetched_paths:\n"
        "                try:\n"
        "                    if path.is_file() and path.stat().st_size > 0:\n"
        "                        return path\n"
        "                except OSError:\n"
        "                    continue\n"
        "    return None\n\n"
        "def _prepare_atlas(params: dict, img_path: Path, atlas_dir: Path) -> Path:\n"
        '    atlas_name = str(params.get("atlas_name") or "Schaefer2018_200")\n'
        '    atlas_path = params.get("atlas_path")\n'
        "    atlas_dir.mkdir(parents=True, exist_ok=True)\n"
        "    if atlas_path:\n"
        "        src = Path(atlas_path).expanduser().resolve()\n"
        "        dst = atlas_dir / src.name\n"
        "        if dst != src:\n"
        "            shutil.copyfile(src, dst)\n"
        "        return dst\n"
        "    if atlas_name.lower() in {'synthetic', 'demo', 'test'}:\n"
        "        img = nib.load(str(img_path))\n"
        "        shape = img.shape[:3]\n"
        "        data = np.zeros(shape, dtype=np.int16)\n"
        "        midpoint = max(1, shape[0] // 2)\n"
        "        data[:midpoint, :, :] = 1\n"
        "        data[midpoint:, :, :] = 2\n"
        '        out_path = atlas_dir / "synthetic_atlas.nii.gz"\n'
        "        nib.save(nib.Nifti1Image(data, affine=img.affine), str(out_path))\n"
        "        return out_path\n"
        "    if atlas_name.lower().startswith('schaefer2018'):\n"
        "        local_atlas = _find_local_templateflow_schaefer(atlas_name, img_path)\n"
        "        if local_atlas is not None:\n"
        "            dst = atlas_dir / local_atlas.name\n"
        "            if dst != local_atlas:\n"
        "                shutil.copyfile(local_atlas, dst)\n"
        "            return dst\n"
        "        atlas = datasets.fetch_atlas_schaefer_2018(\n"
        "            n_rois=_parse_schaefer_rois(atlas_name),\n"
        "            resolution_mm=2,\n"
        "            yeo_networks=_parse_schaefer_networks(atlas_name),\n"
        "            data_dir=str(atlas_dir),\n"
        "        )\n"
        "        src = Path(atlas.maps)\n"
        "        dst = atlas_dir / src.name\n"
        "        if dst != src:\n"
        "            shutil.copyfile(src, dst)\n"
        "        return dst\n"
        "    raise ValueError(f'Unsupported atlas_name for direct recipe: {atlas_name}')\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'output_dir = Path(params["output_dir"]).expanduser().resolve()\n'
        "output_dir.mkdir(parents=True, exist_ok=True)\n"
        'img_path = Path(params["img"]).expanduser().resolve()\n'
        'atlas_dir = output_dir / "atlas"\n'
        'timeseries_dir = output_dir / "timeseries"\n'
        "timeseries_dir.mkdir(parents=True, exist_ok=True)\n"
        "atlas_path = _prepare_atlas(params, img_path, atlas_dir)\n"
        "masker = NiftiLabelsMasker(\n"
        "    labels_img=str(atlas_path),\n"
        '    standardize="zscore_sample" if bool(params.get("standardize", True)) else False,\n'
        "    standardize_confounds=False,\n"
        '    detrend=bool(params.get("detrend", True)),\n'
        '    t_r=params.get("tr"),\n'
        '    low_pass=params.get("low_pass"),\n'
        '    high_pass=params.get("high_pass"),\n'
        "    keep_masked_labels=False,\n"
        ")\n"
        "timeseries = np.asarray(masker.fit_transform(str(img_path)), dtype=float)\n"
        'timeseries_npy = timeseries_dir / "timeseries.npy"\n'
        'timeseries_csv = timeseries_dir / "timeseries.csv"\n'
        "np.save(timeseries_npy, timeseries)\n"
        "np.savetxt(timeseries_csv, timeseries, delimiter=',')\n"
        'kind = str(params.get("connectivity_kind") or "correlation")\n'
        'measure = ConnectivityMeasure(kind=kind, standardize="zscore_sample")\n'
        "matrix = measure.fit_transform([timeseries])\n"
        "matrix, fisher_z_diagnostics = safe_fisher_z(\n"
        "    matrix,\n"
        "    f'rest_connectome_corrmat(kind={kind})',\n"
        "    return_diagnostics=True,\n"
        ")\n"
        'matrix_file = output_dir / "connectivity_matrix.npy"\n'
        "np.save(matrix_file, matrix)\n"
        "outputs = {\n"
        '    "atlas_path": str(atlas_path),\n'
        '    "timeseries": str(timeseries_npy),\n'
        '    "timeseries_csv": str(timeseries_csv),\n'
        '    "matrix": str(matrix_file),\n'
        '    "connectivity_matrix": str(matrix_file),\n'
        "}\n"
        "summary = {\n"
        '    "kind": kind,\n'
        '    "n_timepoints": int(timeseries.shape[0]),\n'
        '    "n_regions": int(timeseries.shape[1]) if timeseries.ndim > 1 else 1,\n'
        '    "fisher_z_applied": True,\n'
        '    "fisher_z_diagnostics": fisher_z_diagnostics,\n'
        "}\n"
        "try:\n"
        "    cov_estimator_obj = getattr(measure, 'cov_estimator_', None) or getattr(measure, 'cov_estimator', None)\n"
        "    cov_estimator_name = type(cov_estimator_obj).__name__ if cov_estimator_obj is not None else None\n"
        "    contract = build_feature_contract(\n"
        "        matrix,\n"
        "        matrix_kind=kind,\n"
        "        source_level='roi_timeseries',\n"
        "        n_rois=int(timeseries.shape[1]) if timeseries.ndim > 1 else 1,\n"
        "        n_timepoints=int(timeseries.shape[0]),\n"
        "        effective_n_timepoints=int(timeseries.shape[0]),\n"
        "        covariance_estimator=cov_estimator_name,\n"
        "        fisher_z_diagnostics=fisher_z_diagnostics,\n"
        "        extras={'atlas_path': str(atlas_path)},\n"
        "    )\n"
        "    outputs['feature_contract'] = str(write_feature_contract(contract, output_dir))\n"
        "except Exception as exc:\n"
        "    summary['feature_contract_warning'] = f'feature_contract sidecar emission failed: {exc!r}'\n"
        "print(json.dumps({'outputs': outputs, 'summary': summary}, indent=2, sort_keys=True))\n"
    )


def _preprocessing_post_qc_script() -> str:
    return (
        "import json\n"
        "from html import escape\n"
        "from pathlib import Path\n\n"
        "import pandas as pd\n\n"
        "def _load_qc_table(qc_tsv: str | None, mriqc_dir: Path, modality: str) -> pd.DataFrame:\n"
        "    if qc_tsv:\n"
        "        return pd.read_csv(qc_tsv, sep='\\t')\n"
        "    candidates = [\n"
        "        mriqc_dir / f'group_{modality}.tsv',\n"
        "        mriqc_dir / f'group_{modality}.csv',\n"
        "        mriqc_dir / 'group_bold.tsv',\n"
        "        mriqc_dir / 'group_T1w.tsv',\n"
        "    ]\n"
        "    table_path = next((path for path in candidates if path.exists()), None)\n"
        "    if table_path is None:\n"
        "        raise FileNotFoundError('MRIQC group table not found')\n"
        "    return pd.read_csv(table_path, sep='\\t' if table_path.suffix == '.tsv' else ',')\n\n"
        "def _write_dashboard(df: pd.DataFrame, output_html: Path, title: str) -> None:\n"
        "    html = [\n"
        "        \"<html><head><meta charset='utf-8'>\",\n"
        "        f'<title>{escape(title)}</title>',\n"
        '        "<style>body{font-family:system-ui,Segoe UI,Arial;margin:24px} table{border-collapse:collapse} td,th{border:1px solid #ddd;padding:6px 8px} th{background:#f6f6f6}</style>",\n'
        '        "</head><body>",\n'
        "        f'<h1>{escape(title)}</h1>',\n"
        "        f'<p>Rows: {df.shape[0]} | Columns: {df.shape[1]}</p>',\n"
        "        df.head(50).to_html(index=False, escape=True),\n"
        '        "</body></html>",\n'
        "    ]\n"
        "    output_html.write_text('\\n'.join(html), encoding='utf-8')\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'output_dir = Path(params["output_dir"]).expanduser().resolve()\n'
        'qc_dir = output_dir / "qc"\n'
        "qc_dir.mkdir(parents=True, exist_ok=True)\n"
        'qc_table_path = qc_dir / "qc_table.csv"\n'
        'outliers_path = qc_dir / "qc_outliers.csv"\n'
        'summary_path = qc_dir / "qc_summary.json"\n'
        'dashboard_path = qc_dir / "index.html"\n'
        "df = _load_qc_table(\n"
        '    params.get("qc_tsv"),\n'
        '    output_dir / "mriqc",\n'
        '    str(params.get("modality") or "bold"),\n'
        ")\n"
        "df.to_csv(qc_table_path, index=False)\n"
        'metric = str(params.get("outlier_metric") or "fd_mean")\n'
        'z_threshold = float(params.get("outlier_z", 3.0))\n'
        "if metric in df.columns:\n"
        "    series = pd.to_numeric(df[metric], errors='coerce')\n"
        "    mu = float(series.mean(skipna=True))\n"
        "    sigma = float(series.std(skipna=True)) or 0.0\n"
        "    if sigma <= 1e-12:\n"
        "        flags = series.notna() & False\n"
        "    else:\n"
        "        flags = ((series - mu) / sigma).abs() >= z_threshold\n"
        "else:\n"
        "    flags = pd.Series([False] * len(df))\n"
        "df_out = df.copy()\n"
        "df_out['outlier'] = flags.fillna(False)\n"
        "df_out.to_csv(outliers_path, index=False)\n"
        "numeric = df_out.select_dtypes(include='number')\n"
        "summary_payload = {\n"
        "    'n_rows': int(df_out.shape[0]),\n"
        "    'n_cols': int(df_out.shape[1]),\n"
        "    'columns': list(df_out.columns),\n"
        "    'metric': metric,\n"
        "    'z_threshold': z_threshold,\n"
        "    'n_outliers': int(flags.sum()),\n"
        "    'numeric_summary': numeric.describe().to_dict() if not numeric.empty else {},\n"
        "}\n"
        "summary_path.write_text(json.dumps(summary_payload, indent=2), encoding='utf-8')\n"
        "_write_dashboard(df_out, dashboard_path, str(params.get('dashboard_title') or 'QC Summary'))\n"
        "print(json.dumps({\n"
        '    "outputs": {\n'
        '        "qc_table": str(qc_table_path),\n'
        '        "outliers_table": str(outliers_path),\n'
        '        "summary": str(summary_path),\n'
        '        "dashboard": str(dashboard_path),\n'
        "    },\n"
        '    "summary": summary_payload,\n'
        "}, indent=2, sort_keys=True, default=str))\n"
    )


def _preprocessing_neurodesk_script() -> str:
    return (
        "import json\n"
        "import subprocess\n"
        "from pathlib import Path\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'output_dir = str(Path(params["output_dir"]))\n'
        "subprocess.run([\n"
        '    "fmriprep",\n'
        '    params["bids_dir"],\n'
        '    str(Path(output_dir) / "fmriprep"),\n'
        '    "participant",\n'
        "], check=True)\n"
        "subprocess.run([\n"
        '    "mriqc",\n'
        '    params["bids_dir"],\n'
        '    str(Path(output_dir) / "mriqc"),\n'
        '    "participant",\n'
        "], check=True)\n"
        'subprocess.run(["python", "post_qc.py"], check=True)\n'
    )


def _preprocessing_container_script(container_images: dict[str, Any]) -> str:
    fmriprep_image = str(container_images.get("fmriprep") or "nipreps/fmriprep:23.2.3")
    mriqc_image = str(container_images.get("mriqc") or "nipreps/mriqc:24.0.2")
    return (
        "import json\n"
        "import subprocess\n"
        "from pathlib import Path\n\n"
        'params = json.loads(Path("params.json").read_text(encoding="utf-8"))\n'
        'bids_dir = str(Path(params["bids_dir"]).resolve())\n'
        'output_dir = str(Path(params["output_dir"]).resolve())\n'
        "docker_mounts = [\n"
        '    "-v", f"{bids_dir}:{bids_dir}",\n'
        '    "-v", f"{output_dir}:{output_dir}",\n'
        "]\n"
        "subprocess.run([\n"
        '    "docker", "run", "--rm", *docker_mounts,\n'
        f'    "{fmriprep_image}",\n'
        "    bids_dir,\n"
        '    str(Path(output_dir) / "fmriprep"),\n'
        '    "participant",\n'
        "], check=True)\n"
        "subprocess.run([\n"
        '    "docker", "run", "--rm", *docker_mounts,\n'
        f'    "{mriqc_image}",\n'
        "    bids_dir,\n"
        '    str(Path(output_dir) / "mriqc"),\n'
        '    "participant",\n'
        "], check=True)\n"
        'subprocess.run(["python", "post_qc.py"], check=True)\n'
    )
