import json
import warnings
import pickle
import tensorflow as tf
import pandas as pd
import numpy as np
from datetime import datetime
from time import time
import argparse
import os
import logging 

from ensemble import Ensemble
from utils.scores import get_scores
from utils.transformations import min_max_normalization, transform_to_sparse
from utils.pareto import get_pareto_optimal_mask

# Set logging
logging.basicConfig(level=logging.DEBUG)

parser = argparse.ArgumentParser(description="Just an example",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("dataset", help="Dataset name", choices={"adult", "german", "fico", "compas"})
parser.add_argument("index", help="Test data index to explain")
args = parser.parse_args()
config = vars(args)

print(config)
print('Dataset to use', config['dataset'])
print('Index to explain', config['index'])


date = datetime.now().strftime(r"%Y-%m-%d")  

# These two parameters should be set in the python call
HYPERPARAMETERS = dict()
HYPERPARAMETERS['DATASET_NAME'] = config['dataset']
HYPERPARAMETERS['INDEX_TO_EXPLAIN'] = int(config['index'])

HYPERPARAMETERS['TRAIN_DATASET_PATH'] = f'data/{HYPERPARAMETERS["DATASET_NAME"]}_train.csv'
HYPERPARAMETERS['TEST_DATASET_PATH'] = f'data/{HYPERPARAMETERS["DATASET_NAME"]}_test.csv'
HYPERPARAMETERS['CONSTRAINTS_PATH'] = f'data/{HYPERPARAMETERS["DATASET_NAME"]}_constraints.json'
HYPERPARAMETERS['MODEL_PATH'] = f'models/{HYPERPARAMETERS["DATASET_NAME"]}_NN/'

HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND'] = 'tensorflow'

HYPERPARAMETERS['SAVE_PATH_SCORES'] = f"experiments/data/{date}/scores/{HYPERPARAMETERS['DATASET_NAME']}_{HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND']}_i{HYPERPARAMETERS['INDEX_TO_EXPLAIN']}_{date}.csv"
HYPERPARAMETERS['SAVE_PATH_VALID_SCORES'] = f"experiments/data/{date}/valid_scores/{HYPERPARAMETERS['DATASET_NAME']}_{HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND']}_i{HYPERPARAMETERS['INDEX_TO_EXPLAIN']}_{date}.csv"
HYPERPARAMETERS['SAVE_PATH_STATS'] = f"experiments/data/{date}/stats/{HYPERPARAMETERS['DATASET_NAME']}_{HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND']}_i{HYPERPARAMETERS['INDEX_TO_EXPLAIN']}_{date}.json"
HYPERPARAMETERS['SAVE_PATH_COUNTERFACTUALS'] = f"experiments/data/{date}/counterfactuals/{HYPERPARAMETERS['DATASET_NAME']}_{HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND']}_i{HYPERPARAMETERS['INDEX_TO_EXPLAIN']}_{date}.csv"
HYPERPARAMETERS['SAVE_PATH_VALID_COUNTERFACTUALS'] = f"experiments/data/{date}/valid_counterfactuals/{HYPERPARAMETERS['DATASET_NAME']}_{HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND']}_i{HYPERPARAMETERS['INDEX_TO_EXPLAIN']}_{date}.csv"

HYPERPARAMETERS['PREFERENCES_RANKING'] = [0, 4, 2, 3, 5, 1]
HYPERPARAMETERS['K_NEIGHBORS_FEASIB'] = 3
HYPERPARAMETERS['K_NEIGHBORS_DISCRIMINATIVE'] = 9

max_index = pd.read_csv(HYPERPARAMETERS['TEST_DATASET_PATH']).shape[0] - 1
assert int(config['index']) <= max_index, f'Passed index is greater than the test dataset size. Please pass index in range 0-{max_index}'

if __name__ == '__main__':
    #PREPARE EXPERIMENT DIRECTORY
    if not os.path.exists(f'experiments/{date}'):
        os.makedirs(f'experiments/{date}/scores')
        os.makedirs(f'experiments/{date}/valid_scores')
        os.makedirs(f'experiments/{date}/stats')
        os.makedirs(f'experiments/{date}/counterfactuals')
        os.makedirs(f'experiments/{date}/valid_counterfactuals')

    experiment_duration = time()

    explained_model_backend = 'tensorflow' # 'sklearn' or 'tensorflow'


    warnings.filterwarnings('ignore', category=UserWarning) #Ignore sklearn "RF fitted with FeatureNames"
    warnings.filterwarnings('ignore', category=FutureWarning) #Ignore sklearn "RF fitted with FeatureNames"

    train_dataset = pd.read_csv(HYPERPARAMETERS['TRAIN_DATASET_PATH'])
    test_dataset = pd.read_csv(HYPERPARAMETERS['TEST_DATASET_PATH'])

    

    with open(HYPERPARAMETERS['CONSTRAINTS_PATH'], 'r') as f:
        constr = json.load(f)
    
    if HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND'] == 'sklearn':
        # SKLEARN
        with open(HYPERPARAMETERS['MODEL_PATH'], 'rb') as f:
            explained_model = pickle.load(f)
    else: 
        # TENSORFLOW
        explained_model = tf.keras.models.load_model(HYPERPARAMETERS['MODEL_PATH'])

    # Make sure that order is correct
    train_dataset = train_dataset[constr['features_order_nonsplit']]
    target_feature_name = constr['target_feature']

    test_dataset_no_target = test_dataset.drop(columns=target_feature_name, inplace=False)

    query_instance = test_dataset_no_target[HYPERPARAMETERS['INDEX_TO_EXPLAIN']:HYPERPARAMETERS['INDEX_TO_EXPLAIN'] + 1]
    HYPERPARAMETERS['QUERY_INSTANCE'] = query_instance.to_dict()
    print(query_instance)

    # INIT ENSEMBLE
    ensemble_init_elapsed_time = time()
    enseble = Ensemble(
        train_dataset=train_dataset, constraints_config_dictionary=constr,
        model_to_explain=explained_model, model_path=HYPERPARAMETERS['MODEL_PATH'],
        list_of_explainers= ['dice', 'cem', 'cfec', 'wachter', 'carla', 'cfproto'] 
        )
    ensemble_init_elapsed_time = time() - ensemble_init_elapsed_time
    HYPERPARAMETERS['ENSEMBLE_INIT_ELAPSED_TIME'] = ensemble_init_elapsed_time

    ensemble_gen_elapsed_time = time()
    cfs, valid_cfs = enseble.generate_counterfactuals(query_instance)
    ensemble_gen_elapsed_time = time() - ensemble_gen_elapsed_time
    HYPERPARAMETERS['ENSEMBLE_GENERATION_ELAPSED_TIME'] = ensemble_gen_elapsed_time


    print('----'*10)
    print('ALL', enseble.get_all_counterfactuals())
    print('----'*10)
    print('VALID', enseble.get_valid_counterfactuals())
    print('----'*10)
    print('VALID ACT', enseble.get_valid_and_actionable_counterfactuals())
    print('----'*10)


    HYPERPARAMETERS['ORIGINAL_X_CLASS'] = test_dataset[HYPERPARAMETERS['INDEX_TO_EXPLAIN']:HYPERPARAMETERS['INDEX_TO_EXPLAIN'] + 1][target_feature_name].to_numpy()[0]

    continous_indices = list()
    categorical_indices = list()
    cols = test_dataset_no_target.columns.tolist()

    for col in constr['continuous_features_nonsplit']:
        continous_indices += [cols.index(col)]

    for col in constr['categorical_features_nonsplit']:
        categorical_indices += [cols.index(col)]


    train_dataset_no_target = train_dataset.drop(columns=target_feature_name)
    train_dataset_no_target_ohe = transform_to_sparse(
        _df = train_dataset_no_target,
        original_df=train_dataset_no_target,
        categorical_features=constr['categorical_features_nonsplit'],
        continuous_features=constr['continuous_features_nonsplit']
    )

    train_dataset_no_target_ohe_norm = min_max_normalization(
        _df=train_dataset_no_target_ohe,
        original_df=train_dataset_no_target,
        continuous_features=constr['continuous_features_nonsplit']
    )

    train_dataset_no_target_ohe_norm = train_dataset_no_target_ohe_norm[constr['features_order_after_split']]
    
    if HYPERPARAMETERS['EXPLAINED_MODEL_BACKEND'] == 'sklearn':
        # SKLEARN
        with open(HYPERPARAMETERS['MODEL_PATH'], 'rb') as f:
            explained_model = pickle.load(f)
    else: 
        # TENSORFLOW
        explained_model = tf.keras.models.load_model(HYPERPARAMETERS['MODEL_PATH'])

    train_preds = np.argmax(explained_model.predict(train_dataset_no_target_ohe_norm.to_numpy()), axis=1)

    scores = get_scores(
        cfs=cfs.drop(columns=[target_feature_name, 'explainer']).to_numpy().astype('<U11'), 
        cf_predicted_classes=cfs[target_feature_name].to_numpy(),
        training_data=train_dataset.drop(columns=target_feature_name).to_numpy().astype('<U11'),
        training_data_predicted_classes=train_preds,
        x = query_instance.to_numpy()[0].astype('<U11'),
        x_predicted_class= test_dataset[HYPERPARAMETERS['INDEX_TO_EXPLAIN']:HYPERPARAMETERS['INDEX_TO_EXPLAIN'] + 1][target_feature_name],
        continous_indices=continous_indices,
        categorical_indices=categorical_indices,
        preferences_ranking=HYPERPARAMETERS['PREFERENCES_RANKING'],
        k_neighbors_feasib=HYPERPARAMETERS['K_NEIGHBORS_FEASIB'], 
        k_neighbors_discriminative=HYPERPARAMETERS['K_NEIGHBORS_DISCRIMINATIVE']
        ).reset_index(drop=True)
    
    scores_valid = get_scores(
        cfs=valid_cfs.drop(columns=[target_feature_name, 'explainer']).to_numpy().astype('<U11'), 
        cf_predicted_classes=valid_cfs[target_feature_name].to_numpy(),
        training_data=train_dataset.drop(columns=target_feature_name).to_numpy().astype('<U11'),
        training_data_predicted_classes=train_preds,
        x = query_instance.to_numpy()[0].astype('<U11'),
        x_predicted_class= test_dataset[HYPERPARAMETERS['INDEX_TO_EXPLAIN']:HYPERPARAMETERS['INDEX_TO_EXPLAIN'] + 1][target_feature_name],
        continous_indices=continous_indices,
        categorical_indices=categorical_indices,
        preferences_ranking=HYPERPARAMETERS['PREFERENCES_RANKING'],
        k_neighbors_feasib=HYPERPARAMETERS['K_NEIGHBORS_FEASIB'], 
        k_neighbors_discriminative=HYPERPARAMETERS['K_NEIGHBORS_DISCRIMINATIVE']
        ).reset_index(drop=True)
    
    print(cfs['explainer'])
    scores['explainer'] = cfs['explainer']
    scores_valid['explainer'] = valid_cfs['explainer']
    #print(scores['explainer'])

    stats = enseble.get_quantitative_stats()
    
    # GET PARETO OPTIMAL STATS
    metric = 'Proximity'
    other_metric = 'K_Feasibility(3)'
    other_other_metric = 'DiscriminativePower(9)'
    HYPERPARAMETERS['PARETO_METRICS'] = [metric, other_metric, other_other_metric]
    optimization_directions = ['min', 'min', 'max']
    all_x = scores[metric].to_numpy()
    all_y = scores[other_metric].to_numpy()
    all_z = scores[other_other_metric].to_numpy()
    to_check = np.array([all_x, all_y, all_z], dtype=np.float64).T
    pareto_mask = get_pareto_optimal_mask(data=to_check, optimization_direction=optimization_directions).astype('bool')
    HYPERPARAMETERS['PARETO_FRONTIERS_ALL'] = int(np.sum(pareto_mask))

    print(scores['explainer'].tolist())

    for explainer in stats['explainers'].keys():
        if explainer in np.unique(scores['explainer']):
            explainer_pareto_count = np.sum(scores[pareto_mask]['explainer'] == explainer)
        else:
            explainer_pareto_count = 0
        stats['explainers'][explainer]['pareto_frontier_count'] = int(explainer_pareto_count)

    # Join both dictionaries
    stats_and_hypers_dic = stats | HYPERPARAMETERS
    stats_and_hypers_dic['ORIGINAL_X_CLASS'] = str(stats_and_hypers_dic['ORIGINAL_X_CLASS'])

    with open(HYPERPARAMETERS['SAVE_PATH_STATS'], 'w') as f:
        json.dump(stats_and_hypers_dic, f, indent=1)

    scores.to_csv(HYPERPARAMETERS['SAVE_PATH_SCORES'], index=False)
    scores_valid.to_csv(HYPERPARAMETERS['SAVE_PATH_VALID_SCORES'], index=False)
    cfs.to_csv(HYPERPARAMETERS['SAVE_PATH_COUNTERFACTUALS'], index=False)
    valid_cfs.to_csv(HYPERPARAMETERS['SAVE_PATH_VALID_COUNTERFACTUALS'], index=False)

    print(scores)
    print(stats)


    experiment_duration = time() - experiment_duration
    print(f'Experiment duration: {experiment_duration}')
