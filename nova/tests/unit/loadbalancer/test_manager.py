import mock
from nova.tests.unit.loadbalancer import fakes
from nova.loadbalancer.manager import LoadBalancer
from nova.objects.compute_node import ComputeNodeList
from nova import db
from nova import exception
from nova import test
from nova import context
import contextlib
from oslo_config import cfg
from nova.loadbalancer import manager
from nova.loadbalancer.balancer.minimizeSD import MinimizeSD
from nova.loadbalancer.underload.mean_underload import MeanUnderload
from nova.loadbalancer.threshold.standart_deviation import Standart_Deviation

import datetime

CONF = cfg.CONF

def compute_node_list_from_dict(d):
    return ComputeNodeList(d)


class LoadBalancerManagerTestCase(test.TestCase, fakes.LbFakes):

    def setUp(self):
        super(LoadBalancerManagerTestCase, self).setUp()
        self.manager = manager.LoadBalancer()
        self.context = context.get_admin_context()
        self.minimizeSD = MinimizeSD()
        self.standart_deviation = Standart_Deviation()

    def test_get_nodes(self):
        self._init_services()
        self.fakes.stats[0].update(memory_used=0, cpu_used_percent=0)
        self.fakes.stats[1].update(memory_used=0, cpu_used_percent=0)
        self._add_compute_nodes()

        with contextlib.nested(
            mock.patch.object(ComputeNodeList,
                              'get_all',
                              return_value=compute_node_list_from_dict(
                                self.fakes.nodes)),
            mock.patch.object(db,
                              'get_compute_node_stats',
                              return_value=self.fakes.stats)
                ) as (mock_get_all, mock_get_compute_node_stats):
                    stats = LoadBalancer().get_nodes(self.context)
                    self.assertEqual(self.fakes.stats, stats)

    def test_suspend_host_badrequest(self):
        self._init_services()
        self._add_compute_nodes()
        self.assertRaises(exception.ComputeHostNotFound,
                          self.manager.underload_class.suspend_host,
                          self.context, 'node12')

    def test_unsuspend_host_badrequest(self):
        self._init_services()
        self.fakes.nodes[0].update(suspend_state='suspending')
        self._add_compute_nodes()
        self.assertRaises(exception.ComputeHostWrongState,
                          self.manager.underload_class.unsuspend_host,
                          self.context, self.fakes.nodes[0])

    def test_clear_compute_stats(self):
        self._init_services()
        self.fakes.stats[0].update(
            created_at=datetime.datetime(2000, 1, 1, hour=1))
        self.fakes.stats[1].update(
            created_at=datetime.datetime(2000, 1, 1, hour=1))
        self._add_compute_nodes()
        delta_time = datetime.datetime.now() - datetime.timedelta(
                        seconds=11100)
        with (
            mock.patch.object(db,
                              'clear_compute_stats')
                ) as (mock_clear_compute_stats):
            db.clear_compute_stats(self.context, delta_time)
            mock_clear_compute_stats.assert_called_once_with(self.context,
                                                             delta_time)

    def test_balancer_standart_deviation_node_exist(self):
        self._init_services()
        self._add_compute_nodes()
        with contextlib.nested(
            mock.patch.object(self.manager.threshold_class,
                              "indicate",
                              return_value=(True, True, True)),
            mock.patch.object(self.manager.balancer_class,
                              "balance"),
            mock.patch.object(self.manager.underload_class,
                              "indicate")
                ) as (mock_treshold_class_indicate,
                      mock_balancer_class_balance,
                      mock_underload_class_indicate):
                    self.manager._balancer(self.context)
                    self.assertFalse(mock_underload_class_indicate.called)
                    self.assertTrue(mock_balancer_class_balance.called)

    def test_balancer_standart_deviation_node_not_exist(self):
        self._init_services()
        self._add_compute_nodes()
        with contextlib.nested(
            mock.patch.object(self.manager.threshold_class,
                              "indicate",
                              return_value=(False, True, True)),
            mock.patch.object(self.manager.balancer_class,
                              "balance"),
            mock.patch.object(self.manager.underload_class,
                              "indicate"),
            mock.patch.object(CONF.loadbalancer,
                              "enable_underload",
                              return_value=True)
                ) as (mock_treshold_class_indicate,
                      mock_balancer_class_balance,
                      mock_underload_class_indicate,
                      mock_conf_enable_underload):
                    self.manager._balancer(self.context)
                    self.assertTrue(mock_underload_class_indicate.called)
                    self.assertFalse(mock_balancer_class_balance.called)
