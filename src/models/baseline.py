from __future__ import annotations

import csv
import json
import statistics
import time
from pathlib import Path

import joblib
import mlflow
import matplotlib
import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, precision_recall_fscore_support
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data' / 'processed'
OUT = ROOT / 'experiments' / 'baseline'
TEMP = ROOT / 'work' / 'baseline_models'


def build_models(config: dict) -> dict:
    tfidf_params = config['tfidf']
    vectorizer = lambda: TfidfVectorizer(
        ngram_range=tuple(tfidf_params['ngram_range']),
        min_df=tfidf_params['min_df'],
        sublinear_tf=tfidf_params['sublinear_tf'],
        lowercase=tfidf_params['lowercase'],
        stop_words=tfidf_params['stop_words'],
        token_pattern=tfidf_params['token_pattern'],
    )
    return {
        'majority': DummyClassifier(strategy=config['majority']['strategy']),
        'tfidf_logistic_regression': Pipeline([
            ('tfidf', vectorizer()),
            ('classifier', LogisticRegression(**config['logistic_regression'])),
        ]),
        'tfidf_linear_svm': Pipeline([
            ('tfidf', vectorizer()),
            ('classifier', LinearSVC(**config['linear_svm'])),
        ]),
        'tfidf_multinomial_nb': Pipeline([
            ('tfidf', vectorizer()),
            ('classifier', MultinomialNB(**config['naive_bayes'])),
        ]),
    }


def main() -> None:
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    config_path = ROOT / 'configs' / 'baseline.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    tracking_db = ROOT / config['tracking']['database']
    train = pd.read_csv(DATA / 'train.csv')
    val = pd.read_csv(DATA / 'validation.csv')
    X_train, y_train = train['text'], train['category']
    X_val, y_val = val['text'], val['category']
    labels = sorted(set(y_train) | set(y_val))
    OUT.mkdir(parents=True, exist_ok=True); TEMP.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{tracking_db.as_posix()}")
    mlflow.set_experiment(config['tracking']['experiment'])
    results = []
    predictions = {}
    run_ids = {}
    config_key = {
        'majority': 'majority',
        'tfidf_logistic_regression': 'logistic_regression',
        'tfidf_linear_svm': 'linear_svm',
        'tfidf_multinomial_nb': 'naive_bayes',
    }
    for name, model in build_models(config).items():
        t0 = time.perf_counter(); model.fit(X_train, y_train); fit_seconds = time.perf_counter() - t0
        model.predict(X_val.iloc[:min(config['timing']['warmup_requests'], len(X_val))])
        timings = []
        for _ in range(config['timing']['full_validation_repeats']):
            start = time.perf_counter(); pred = model.predict(X_val); timings.append(time.perf_counter() - start)
        single_timings = []
        single_queries = X_val.iloc[:min(config['timing']['single_request_sample_size'], len(X_val))].tolist()
        for _ in range(config['timing']['single_request_repeats']):
            for text in single_queries:
                start = time.perf_counter(); model.predict([text]); single_timings.append(time.perf_counter() - start)
        y_pred = np.asarray(pred); predictions[name] = y_pred
        precision, recall, f1, _ = precision_recall_fscore_support(y_val, y_pred, labels=labels, zero_division=0)
        weighted = precision_recall_fscore_support(y_val, y_pred, labels=labels, average='weighted', zero_division=0)
        accuracy = accuracy_score(y_val, y_pred)
        artifact = TEMP / f'{name}.joblib'; joblib.dump(model, artifact)
        report = classification_report(y_val, y_pred, labels=labels, output_dict=True, zero_division=0)
        pd.DataFrame(report).T.to_csv(OUT / f'{name}_classification_report.csv', index_label='label')
        pd.DataFrame(confusion_matrix(y_val, y_pred, labels=labels), index=labels, columns=labels).to_csv(OUT / f'{name}_confusion_matrix.csv', index_label='true_label')
        results.append({
            'model': name,
            'accuracy': float(accuracy),
            'macro_precision': float(np.mean(precision)),
            'macro_recall': float(np.mean(recall)),
            'macro_f1': float(np.mean(f1)),
            'weighted_precision': float(weighted[0]),
            'weighted_recall': float(weighted[1]),
            'weighted_f1': float(weighted[2]),
            'fit_seconds': float(fit_seconds),
            f"batch_inference_seconds_median_{config['timing']['full_validation_repeats']}_runs": float(statistics.median(timings)),
            'batch_amortized_ms_per_request': float(statistics.median(timings) * 1000 / len(X_val)),
            'single_query_latency_p50_ms': float(np.percentile(single_timings, 50) * 1000),
            'single_query_latency_p95_ms': float(np.percentile(single_timings, 95) * 1000),
            'serialized_model_kb': float(artifact.stat().st_size / 1024),
            'runtime_memory_measured': False,
        })
        report_path = OUT / f'{name}_classification_report.csv'
        confusion_path = OUT / f'{name}_confusion_matrix.csv'
        with mlflow.start_run(run_name=name) as run:
            run_ids[name] = run.info.run_id
            results[-1]['mlflow_run_id'] = run.info.run_id
            mlflow.log_params({
                'model': name,
                'sklearn_version': sklearn.__version__,
                'tfidf_ngram_range': str(config['tfidf']['ngram_range']),
                'tfidf_min_df': config['tfidf']['min_df'],
                'tfidf_sublinear_tf': config['tfidf']['sublinear_tf'],
                **{f'model.{k}': str(v) for k, v in config[config_key[name]].items()},
            })
            mlflow.set_tags({'dataset': 'BANKING77', 'evaluation_split': 'validation', 'config': 'configs/baseline.json'})
            mlflow.log_metrics({k: v for k, v in results[-1].items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
            mlflow.log_artifact(str(config_path), artifact_path='config')
            mlflow.log_artifact(str(ROOT / 'experiments' / 'baseline' / 'split_manifest.json'), artifact_path='data')
            mlflow.log_artifact(str(ROOT / 'data' / 'raw' / 'source_manifest.json'), artifact_path='data')
            mlflow.log_artifact(str(report_path), artifact_path='evaluation')
            mlflow.log_artifact(str(confusion_path), artifact_path='evaluation')
            mlflow.log_artifact(str(artifact), artifact_path='serialized_model')
    results.sort(key=lambda r: r['macro_f1'], reverse=True)
    run_info = {'sklearn_version': sklearn.__version__, 'config': str(config_path.relative_to(ROOT)).replace('\\', '/'), 'validation_rows': len(val), 'train_rows': len(train), 'models': results}
    (OUT / 'results.json').write_text(json.dumps(run_info, ensure_ascii=False, indent=2), encoding='utf-8')
    pd.DataFrame(results).to_csv(OUT / 'results.csv', index=False)

    best = results[0]['model']; y_best = predictions[best]
    mistakes = val.loc[np.asarray(y_val != y_best)].copy()
    mistakes['predicted_category'] = y_best[np.asarray(y_val != y_best)]
    mistakes.to_csv(OUT / 'best_model_misclassifications.csv', index=False)
    pair_counts = mistakes.groupby(['category', 'predicted_category']).size().sort_values(ascending=False).head(30)
    with (OUT / 'top_confusions.csv').open('w', newline='', encoding='utf-8') as f:
        writer=csv.writer(f); writer.writerow(['true_category','predicted_category','count'])
        for (true_label,pred_label),count in pair_counts.items(): writer.writerow([true_label,pred_label,int(count)])
    matrix = confusion_matrix(y_val, y_best, labels=labels)
    figure, axis = plt.subplots(figsize=(10, 9), dpi=180)
    image = axis.imshow(matrix, interpolation='nearest', cmap='Blues')
    ticks = list(range(0, len(labels), 10))
    axis.set_xticks(ticks, [str(i) for i in ticks], fontsize=8)
    axis.set_yticks(ticks, [str(i) for i in ticks], fontsize=8)
    axis.set_xlabel('Predicted intent index (alphabetical class order)')
    axis.set_ylabel('True intent index (alphabetical class order)')
    axis.set_title('Linear SVM confusion matrix on validation')
    figure.colorbar(image, ax=axis, label='Number of validation requests')
    figure.tight_layout()
    figure.savefig(OUT / 'tfidf_linear_svm_confusion_matrix.png', bbox_inches='tight')
    plt.close(figure)
    mlflow_client = mlflow.tracking.MlflowClient()
    mlflow_client.log_artifact(run_ids[best], str(OUT / 'top_confusions.csv'), artifact_path='error_analysis')
    mlflow_client.log_artifact(run_ids[best], str(OUT / 'best_model_misclassifications.csv'), artifact_path='error_analysis')
    mlflow_client.log_artifact(run_ids[best], str(OUT / 'tfidf_linear_svm_confusion_matrix.png'), artifact_path='evaluation')
    print(json.dumps({'sklearn_version': sklearn.__version__, 'validation_rows':len(val), 'results':results, 'top_confusions':[(a,b,int(n)) for (a,b),n in pair_counts.head(10).items()]},ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
