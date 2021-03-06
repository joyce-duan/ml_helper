'''
    pd.set_option('max_colwidth',500)
    sys.stdout.flush()

'''

import sys
import numpy as np
import pandas as pd
import scipy as sp
from scipy.sparse import isspmatrix
import matplotlib.pyplot as plt


from sklearn.pipeline import Pipeline
from sklearn.grid_search import GridSearchCV
from sklearn.base import BaseEstimator

from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.feature_extraction.text import TfidfTransformer

from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize
from sklearn.preprocessing import StandardScaler

from sklearn.feature_selection import SelectKBest
from sklearn.feature_selection import chi2

from sklearn import linear_model
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from sklearn.naive_bayes import GaussianNB
from sklearn.naive_bayes import MultinomialNB
from sklearn.lda import LDA
from sklearn.qda import QDA

from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier

from sklearn.metrics import roc_curve, classification_report, roc_auc_score
from sklearn.metrics import accuracy_score, precision_score, recall_score
from sklearn.metrics import f1_score
from sklearn.metrics import confusion_matrix
from sklearn.cross_validation import train_test_split

import pickle
import time
from collections import Counter
import random 

import pprint
import logging

from model_evaluation.grid_search import get_grid_search_score_df # score_grid_search

# Display progress logs on stdout
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

def baseline_model_gbc(df, xnames, yname):
    clf = GradientBoostingClassifier()
    m = cross_val_score(clf, df[xnames], df[yname], scoring = 'roc_auc', cv = 5)
    print m.mean(), m

def build_rfc():
    d = {'min_samples_leaf': 7, 'min_samples_split': 3, 'criterion': 'entropy', 'max_features': 9, 'max_depth': 11, 'class_weight': {0: 1, 1: 1} }
    clf = RandomForestClassifier(max_depth = 15, n_estimators = 250, min_samples_leaf =5 )
    clf.set_params(**d)
    return clf


def calibrate_prob(y_true, y_score, bins=10, normalize=False):
    '''
    modified from http://jmetzen.github.io/2014-08-16/reliability-diagram.html

    returns two arrays which encode a mapping from predicted probability to empirical probability.
    For this, the predicted probabilities are partitioned into equally sized
    bins and the mean predicted probability and the mean empirical probabilties
    in the bins are computed. For perfectly calibrated predictions, both
    quantities whould be approximately equal (for sufficiently many test
    samples).

    Note: this implementation is restricted to binary classification.

    Parameters
    ----------
    y_true : array, shape = [n_samples]
        True binary labels (0 or 1).
    y_score : array, shape = [n_samples]
        Target scores, can either be probability estimates of the positive
        class or confidence values. If normalize is False, y_score must be in
        the interval [0, 1]

    bins : int, optional, default=10
        The number of bins into which the y_scores are partitioned.
        Note: n_samples should be considerably larger than bins such that
              there is sufficient data in each bin to get a reliable estimate
              of the reliability
    normalize : bool, optional, default=False
        Whether y_score needs to be normalized into the bin [0, 1]. If True,
        the smallest value in y_score is mapped onto 0 and the largest one
        onto 1.

    -------
    y_score_bin_mean : array, shape = [bins]
        The mean predicted y_score in the respective bins.

    empirical_prob_pos : array, shape = [bins]
        The empirical probability (frequency) of the positive class (+1) in the
        respective bins.
    '''    
    if normalize:  # Normalize scores into bin [0, 1]
        y_score = (y_score - y_score.min()) / (y_score.max() - y_score.min())

    bin_width = 1.0 / bins
    bin_centers = np.linspace(0, 1.0 - bin_width, bins) + bin_width / 2

    y_score_bin_mean = np.empty(bins)
    empirical_prob_pos = np.empty(bins)
    for i, threshold in enumerate(bin_centers):
        # determine all samples where y_score falls into the i-th bin
        bin_idx = np.logical_and(threshold - bin_width / 2 < y_score,
            y_score <= threshold + bin_width / 2)
        # Store mean y_score and mean empirical probability of positive class
        y_score_bin_mean[i] = y_score[bin_idx].mean()
        empirical_prob_pos[i] = y_true[bin_idx].mean()
    return y_score_bin_mean, empirical_prob_pos

class ClassifierTestor(object):
    '''
    run all typical models using default setting and find the best k 
    '''
    metric_names = [
     'accuracy'
    ,'precision'
    ,'recall'
    ,'f1'
    ]

    dict_estimator = {
            'LogisticRegression':linear_model.LogisticRegression()            
            , 'SGDClassifier': linear_model.SGDClassifier( )  # default 'hinge' svm,
            , 'SGDC_lr': linear_model.SGDClassifier(loss='log') #  'log' logistic regression
            , 'MultinomialNB':MultinomialNB()
            , 'SVC':SVC()
            , 'RF':RandomForestClassifier( ) # n_estimators=500)
            , 'AdaBoostClassifier':AdaBoostClassifier(  ) # n_estimators=500, learning_rate=0.1) 
            , 'KNN':KNeighborsClassifier(11)
            ,'SVC_linear':SVC(kernel="linear", C=1)
            ,'SVC_rbf':SVC( kernel='rbf')
            , 'SVC_poly':SVC(kernel='poly')
            , 'GaussianNB':GaussianNB()
            , 'GBC':GradientBoostingClassifier( ) # n_estimators = 500, learning_rate = 0.02) 
            ,'LDA':LDA()
            ,'QDA':QDA()
            }

    def __init__ (self, estimators = [], scoring = 'accuracy'):
        '''
        INPUT:
            estimators: a list of names or a dictonary
            scoring: 'accuracy', 'roc_auc'
        '''
        self.scoring = scoring
        if  not estimators:
            self.estimators = ClassifierTestor.dict_estimator 
        elif type(estimators) == list:
            self.estimators = dict([(k, ClassifierTestor.dict_estimator[k]) for k in estimators])
        else:
            self.estimators = estimators
        if self.scoring == 'roc_auc':
            self.metric_names = [self.scoring] 
        else:
            self.metric_names = ClassifierTestor.metric_names

    def _reorder(self, names):
        slow_methods = [ 'SVC_rbf', 'SVC', 'GBC']
        m_to_add = []
        for s in slow_methods:
            if s in names:
                i = names.index(s)
                del(names[i])
                m_to_add.append(s)
        names.extend(m_to_add)
        return names

    def fit_predict_proba(self, train_X, test_X, train_y, test_y):
        #self.fit(train_X, train_y)
        estimator_names = self.estimators.keys()
        estimator_names = self._reorder(estimator_names)
        self.estimator_names = estimator_names

        print estimator_names
        print ', '.join(self.metric_names)       

        metrics_all = []
        #for k, estimator in self.estimators.iteritems():

        if isspmatrix(train_X):
            test_X_full = test_X.todense()
            train_X_full = train_X.todense()
        else:
            test_X_full = test_X
            train_X_full = train_X

        for k in estimator_names:
            estimator = self.estimators[k]
            print '\n%s' % (k)
            t0 = time.time()            
            try:
                if k in ['GaussianNB','GBC', 'LDA', 'QDA']:
                    train_X_f = train_X_full
                    test_X_f = test_X_full
                else:
                    train_X_f = train_X
                    test_X_f = test_X
                self.estimators[k]  = estimator.fit(train_X_f, train_y)

                if 'Classifier' in estimator.__class__.__name__:
                    test_y_pred_prob = estimator.predict_proba(test_X_f)
                else:
                    test_y_pred_prob = np.zeros((len(test_y),2))               
                    test_y_pred_prob[:,1] = estimator.predict(test_X_f).T

                #metrics = [accuracy_score(test_y, test_y_pred) 
                #,precision_score(test_y, test_y_pred) #, average='binary')
                #, recall_score(test_y, test_y_pred)
                #, f1_score(test_y, test_y_pred)]
                metrics = [roc_auc_score(test_y, test_y_pred_prob[:,1])]
                str_metrics = ['%.3f' % (m) for m in metrics]
                print '%s %s'  %(k, str_metrics)
            except:
                print 'errror in model %s'  % (k)
                metrics = [np.nan] * len(self.metric_names)
            t1 = time.time() # time it
            metrics_all.append([k] + metrics + [(t1-t0)/60])
            #print "finish in  %4.4fmin for %s " %((t1-t0)/60,k)
        self.df_score = pd.DataFrame(metrics_all, columns = ['model'] + self.metric_names + ['time'])
        print "\n"

    def fit_predict(self, train_X, test_X, train_y, test_y):
        '''
        X: feature matrix
        '''
        # convert to full matrix, required for GBC

        estimator_names = self.estimators.keys()
        estimator_names = self._reorder(estimator_names)

        print estimator_names
        print ', '.join(self.metric_names)

        if isspmatrix(train_X):
            train_X_full = train_X.todense()
            test_X_full = test_X.todense()
        else:
            train_X_full = train_X
            test_X_full = test_X

        metrics_all = []
        #for k, estimator in self.estimators.iteritems():

        for k in estimator_names:
            estimator = self.estimators[k]
            print '\n%s' % (k)
            t0 = time.time()
            try:
                if k in ['GaussianNB','GBC', 'LDA', 'QDA']:
                    train_X_f = train_X_full
                    test_X_f = test_X_full
                else:
                    train_X_f = train_X
                    test_X_f = test_X
                estimator = estimator.fit(train_X_f, train_y)
                test_y_pred = estimator.predict(test_X_f)
                metrics = [accuracy_score(test_y, test_y_pred) 
                ,precision_score(test_y, test_y_pred) #, average='binary')
                , recall_score(test_y, test_y_pred)
                , f1_score(test_y, test_y_pred)]
                str_metrics = ['%.3f' % (m) for m in metrics]
                print '%s %s'  %(k, str_metrics)
            except:
                print 'errror in model %s'  % (k)
                metrics = [np.nan] * len(metric_names)
            t1 = time.time() # time it
            metrics_all.append([k] + metrics + [(t1-t0)/60])
            print "finish in  %4.4fmin for %s " %((t1-t0)/60,k)
        self.df_score = pd.DataFrame(metrics_all, columns = ['model'] + self.metric_names + ['time'])
        print "\n"


    def score(self):
        #self.df_score.sort('accuracy', ascending=False, inplace = True)
        self.df_score.sort(self.scoring, ascending=False, inplace = True)
        return self.df_score


class ClassifierSelector(object):
    '''
    quick select by testing hyper-parameter space of a few classifier 
    '''
    #   ['svm', 'rf','knn','lr','gbc']
    dict_model  = {'svm': SVC(),
    'rf': RandomForestClassifier()
    ,"knn": KNeighborsClassifier()
    ,'lr': linear_model.LogisticRegression()
    , 'sgdc': linear_model.SGDClassifier()
    ,'gbc': GradientBoostingClassifier() 
    ,'adabc': AdaBoostClassifier()
    } 

    dict_params = {
    'svm':[
        {'clf__C': [1, 10], 'clf__kernel': ['linear']},
        {'clf__C': [1, 10]  # default gamma is 0.0 then 1/n_features
        , 'clf__kernel': ['rbf']},
        {'clf__kernel': ['poly'], 'clf__degree': [ 2, 3]}
        ]
    ,'rf': [{"clf__n_estimators": [100, 250]
        , 'clf__max_depth':[20]
        , 'clf__min_samples_leaf':[5]}]
    ,'knn': [{"clf__n_neighbors": [ 5, 10, 20]}]
    , 'lr': [ {'clf__C': [1, 10, 100]} ]
    , 'gbc': [{'clf__learning_rate': [ 0.1] # default 0.1
            , 'clf__n_estimators': [100, 300] #default 100
            }]
    ,'sgdc': [{
        'clf__loss':['log'],'clf__penalty':["elasticnet"]
        , 'clf__shuffle':[True]
        ,   'clf__alpha':[0.001, 0.0001, 0.00001]
        ,  'clf__n_iter':[20]}]
    ,'adabc':[{
        'clf__n_estimators': [50, 200, 500] # default 50
        , 'clf__learning_rate': [0.1, 0.5] #, 1.0]   #default 1.0
        }]
    , 'gbc': [{
        'clf__learning_rate': [ 0.1, 0.01] # default 0.1
        , 'clf__n_estimators': [100, 500] #default 100
        }]
    , 'lr': [ {'clf__C': [0.01,  1, 10],  # default: 1.0 inverse regularion strength
          'clf__class_weight': [None, 'auto'],
          'clf__tol': [ 1e-3, 1e-4, 1e-5]  # default 1e-4 0.0001
          }]
    }    

    def __init__(self, model_names, dict_params = {}, scoring = 'accuracy'):
        if model_names:
            self.models = dict([ (m, self.dict_model[m]) for m in model_names])
        else:
            self.models = self.dict_model 
        if dict_params:
            self.params = dict_params
        else:
            self.params = self.dict_params
        self.grid_searches = {}
        self.time_taken = {}
        self.scoring = scoring

    def fit(self, x_train, y_train, cv=3, scoring= None,  refit=True, n_jobs=-1, verbose=1):
        if scoring is None:
            scoring = self.scoring
        print self.models.keys()

        if isspmatrix(x_train):
            train_X_full = x_train.todense()
        else:
            train_X_full = x_train

        for model_name in self.models:
            if model_name in ('gbc','lda', 'qda'):
                x_train_f = train_X_full
            else:
                x_train_f = x_train

            print '\n\n%s' % (model_name)
            print self.params[model_name]
            t0 = time.time()
            pipeline = Pipeline([
            ('clf', self.models[model_name])
            ]) 
            gs = GridSearchCV(pipeline, self.params[model_name]\
                , cv=cv, n_jobs=n_jobs, 
                              verbose=verbose, scoring=scoring, refit=refit)
            gs.fit(x_train_f,y_train)
            print 'Best score  % .3f' % (gs.best_score_) , gs.best_params_,
            self.grid_searches[model_name] = gs    
            t1 = time.time() # time it
            self.time_taken[model_name] = (t1-t0)/60
        print 

    def score(self, sortby=['mean']):
        '''
        score of all the grid search results model, name
        '''
        lst_score = []
        for model_name, gs in  self.grid_searches.iteritems():
             gs_scores = gs.grid_scores_
             for grid_score in gs_scores:
                scores = grid_score.cv_validation_scores
                params =   grid_score.parameters
                lst_score.append([model_name, np.mean(scores), min(scores), max(scores), np.std(scores), params, self.time_taken[model_name]] )
        self.df_score = pd.DataFrame(lst_score, columns=['model','mean','min','max','std', 'param','minutes'])  
        self.df_score.sort(sortby + ['mean'], inplace=True, ascending=False)
        return self.df_score 

    def score_predict(self, x_test, y_test):
        l = []
        if isspmatrix(x_test):
            test_X_full = x_test.todense()
        else:
            test_X_full = x_test

        for model_name in self.models:
            if model_name in ('gbc','lda', 'qda'):
                x_test_f = test_X_full
            else:
                x_test_f = x_test
        for model_name, gs in  self.grid_searches.iteritems():
            estimator = gs.best_estimator_
            #print estimator
            if self.scoring == 'roc_auc':            
                test_y_pred_proba = estimator.predict_proba(x_test_f)
                a = roc_auc_score(y_test, test_y_pred_proba)
            elif self.scoring == 'accuracy':
                test_y_pred = estimator.predict(x_test_f)
                a = accuracy_score(y_test, test_y_pred)  
            else:
                print 'ERROR: scoring method not defined %s' % (self.scoring)             

            l.append([model_name, a])
        #print l
        return l

class ClassifierOptimizer(object):
    '''
    hyper parameter search for 1 classifier
    feature: can be text if added pipeline steps
    '''
    dict_model  = {'svm': SVC()
    ,'rf': RandomForestClassifier()
    ,"knn": KNeighborsClassifier()
    ,'lr': linear_model.LogisticRegression()
    , 'sgdc': linear_model.SGDClassifier()
    ,'gbc': GradientBoostingClassifier() 
    } # <== change here
    # pipeline parameters to automatically explore and tune
    
    dict_params = {'svm':[
    {'clf__C': [1, 10, 100, 1000], 'clf__kernel': ['linear']},
    {'clf__C': [1, 10, 100, 1000], 'clf__gamma': [0.1, 0.01, 0.001]  # default gamma is 0.0 then 1/n_features
    , 'clf__kernel': ['rbf']},
    {'clf__kernel': ['poly'], 'clf__degree': [1, 2, 3, 4]}
    ], 
    'rf': [{"clf__n_estimators": [100, 250]
            , 'clf__max_depth':[20]
        , 'clf__min_samples_leaf':[5] }], 
    'knn': [{"clf__n_neighbors": [1, 3, 5, 10, 20]}]
    , 'lr': [ {'clf__C': [0.0001, 0.001, 0.01, 0.5, 1, 10, 100, 1000],  # default: 1.0 inverse regularion strength
          'clf__class_weight': [None, 'auto'],
          'clf__tol': [ 1e-3, 1e-4, 1e-5, 1e-6],#, 1e-7] } ] # default 1e-4 0.0001
          'clf__penalty':['l2','l1']
          }]
    , 'gbc': [{'clf__learning_rate': [0.8, 0.1, 0.05, 0.02, 0.01] # default 0.1
        , 'clf__max_depth': [3,8]  #default 3; 2:main effect only; 3: 2 variable interaction; [4,8] typical case
        , 'clf__min_samples_leaf': [5, 10] #default 1
        , 'clf__max_features': [1.0, 0.3] #default None 1.0
        , 'clf__n_estimators': [300] #default 100
        }]
    , 'sgdc':[{'clf__loss':['log'] # logistic regression
        ,'clf__penalty':["elasticnet"]  #default l2  none, l2, l1, or elasticnet
        , 'clf__shuffle':[True]  #default True
        , 'clf__alpha':[0.001, 0.0001, 0.00001]  # default 0.0001
        ,  'clf__n_iter':[5, 8]}]  # no. of passes over the data The number of iterations is set to 1 if using partial_fit. Defaults to 5. optimal:  n_iter = np.ceil(10**6 / n) n=size of training set
    }    
    '''
    SGDClassifier
    params_grid = {"clf__n_iter": [5, 8, 10, 15],
              "clf__alpha": [1e-7, 1e-6, 1e-5, 0.0001, 0.001, 0.01, 0.1, 1],
              "clf__penalty": ["none", "l1", "l2"],
              'clf__loss': ['log']}
    '''

    #dict_params = {'svm':{'classifier__C': [1, 10, 100, 1000], 'classifier__kernel': ['linear']}}
    def __init__(self, clfname):
        self.clfname= clfname
        #print ClassifierOptimizer.dict_params
        self.params = ClassifierOptimizer.dict_params[self.clfname]
        self.clf_func = ClassifierOptimizer.dict_model[self.clfname]
        self.parameters = None
        self.pipeline = None

    def get_clf(self):
        return self.clf_func

    def set_params(self, params):
        '''
            - INPUT: list of hash 
            params = [{"clf__n_estimators": [250] 
            , 'clf__max_depth':[10, 20, 30]}]
        '''
        self.params = params

    def add_pipleline(self,lst_pipeline = [], params = None ):
        ''' 
        #run set_params before add_pipeline
        params_grid = [{
              "clf__penalty": ["none", "l1", "l2"],
              'clf__loss': ['log']}]              
        optmizer = ClassifierOptimizer('sgdc') # linear_model.SGDClassifier(loss='log') 
        optmizer.set_params(params_grid)
        optmizer.add_pipleline([("scalar",  StandardScaler())])

        '''
        self.pipeline = Pipeline(
            lst_pipeline + 
            [('clf', self.get_clf())])

        print("pipeline:", [name for name, _ in self.pipeline.steps])
        self.parameters = self.params

        if params:
            self.parameters = [ dict(d, **params) for d in self.params]
        print self.parameters

    def optimize(self, train_txt,  train_y, cv = 3, scoring = None, n_jobs = 1):    
        '''
        train_txt: can be text if add_pipeline
        '''
        if self.parameters is None:
            self.parameters = self.params
        if self.pipeline is None:
            self.pipeline = Pipeline([
            ('clf', self.get_clf())])            

        print self.get_clf().__class__.__name__
        print("Performing grid search")
        print("parameters:")
        pprint.pprint(self.parameters)

        pnames = {}
        for p in self.parameters:
            for k in p:
                pnames[k] =1
        print 'parameters to optimize: ', pnames.keys()

        self.grid_search = GridSearchCV(self.pipeline, self.parameters, n_jobs=n_jobs \
            , verbose=1, cv = cv, scoring = scoring)

        t0 = time.time()
        self.grid_search.fit(train_txt, train_y)

        print("estimator Best score: %0.5f" % (self.grid_search.best_score_))
        print("Best parameters set:")
        best_parameters = self.grid_search.best_estimator_.get_params()
        #print best_parameters
        for param_name, v in best_parameters.iteritems():
            if param_name in pnames:
                print("\t%s: %r" % (param_name, v))
        #print self.grid_search.grid_scores_

        t1 = time.time() # time it
        print "finish in  %4.4fmin for %s " %((t1-t0)/60,'optimize')
        return self.grid_search

    # def get_score(self):
    def get_score_gridsearchcv(self):
        #self.df_score = score_grid_search(self.grid_search)
        self.df_score = get_grid_search_score_df(self.grid_search)
        return self.df_score

    def score_predict(self, test_txt, test_y):
        estimator = self.grid_search.best_estimator_
        test_y_pred = estimator.predict(test_txt)
        a = accuracy_score(test_y, test_y_pred)
        #print a
        return a, test_y_pred

    def get_best_estimator(self):
        '''
        dictionary of named steps in the pipeline
        '''
        return self.grid_search.best_estimator_.named_steps

    def get_best_classifier(self):
        '''
        instance of the classification method
        '''
        return self.grid_search.best_estimator_.named_steps['clf']
