'''
Test functions for Skewness
'''

import numpy as np

from ..statistics import StatMoments, StatMomentsDistance
from ._testing_data import dataset1, dataset2, computed_data, computed_distances

class testSkewness():

    def __init__(self):
        self.dataset1 = dataset1
        self.dataset2 = dataset2
        self.computed_data = computed_data
        self.computed_distances = computed_distances
        self.tester = None

    def test_Skewness_method(self):
        self.tester = StatMomentsDistance(dataset1["integrated_intensity"][0], dataset2["integrated_intensity"][0], 5).moments1.skewness_array 
        assert np.allclose(self.tester, self.computed_data['skewness_val'])

    def test_Skewness_distance(self):
        self.tester = StatMomentsDistance(dataset1["integrated_intensity"][0], dataset2["integrated_intensity"][0], 5).distance_metric().skewness_distance
        assert np.allclose(self.tester, self.computed_distances['skewness_distance'])