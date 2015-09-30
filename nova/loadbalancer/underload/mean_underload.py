# Copyright (c) 2015 Servionica, LLC
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from nova import db
from nova import objects
from nova import utils as nova_utils
from nova.loadbalancer.underload.base import Base
from nova.loadbalancer.balancer.minimizeSD import MinimizeSD
from nova.loadbalancer import utils
from nova.compute import rpcapi as compute_api

from oslo_log import log as logging
from oslo_config import cfg

lb_opts = [
    cfg.FloatOpt('threshold_cpu',
                 default=0.05,
                 help='CPU Underload Threshold'),
    cfg.FloatOpt('threshold_memory',
                 default=0.05,
                 help='Memory Underload Threshold'),
    cfg.FloatOpt('unsuspend_cpu',
                 default=0.40,
                 help='CPU Unsuspend Threshold'),
    cfg.FloatOpt('unsuspend_memory',
                 default=0.40,
                 help='CPU Unsuspend Threshold')
]


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.register_opts(lb_opts, 'loadbalancer_mean_underload')


class MeanUnderload(Base):

    def __init__(self):
        self.compute_rpc = compute_api.ComputeAPI()
        self.minimizeSD = MinimizeSD()

    def indicate(self, context, **kwargs):
        extra = kwargs.get('extra_info')
        cpu_th = CONF.loadbalancer_mean_underload.threshold_cpu
        memory_th = CONF.loadbalancer_mean_underload.threshold_memory
        compute_nodes = db.get_compute_node_stats(context, use_mean=True)
        if len(compute_nodes) <= 1:
            self.unsuspend_host(context, extra_info=extra)
            return

        instances = []
        for node in compute_nodes:
            node_instances = db.get_instances_stat(context,
                                                   node['hypervisor_hostname'])
            instances.extend(node_instances)
        compute_stats = utils.fill_compute_stats(instances, compute_nodes)
        host_loads = utils.calculate_host_loads(compute_nodes, compute_stats)
        for node in host_loads:
            memory = host_loads[node]['mem']
            cpu = host_loads[node]['cpu']
            if (cpu < cpu_th) or (memory < memory_th):
                compute_id = filter(lambda x: x['hypervisor_hostname'] == node,
                                    compute_nodes)[0]['compute_id']
                LOG.debug('underload is needed')
                db.compute_node_update(context, compute_id,
                                       {'suspend_state': 'suspending'})
                migrated = self.minimizeSD.migrate_all_vms_from_host(context,
                                                                     node)
                if migrated:
                    return True
                db.compute_node_update(context, compute_id,
                                       {'suspend_state': 'not suspended'})
        self.unsuspend_host(context, extra_info=extra)       
        
    def unsuspend_host(self, context, extra_info=None):
        cpu_mean = extra_info.get('cpu_mean')
        ram_mean = extra_info.get('ram_mean')
        unsuspend_cpu = CONF.loadbalancer_mean_underload.unsuspend_cpu
        unsuspend_ram = CONF.loadbalancer_mean_underload.unsuspend_memory
        if cpu_mean > unsuspend_cpu or ram_mean > unsuspend_ram:
            compute_nodes = db.get_compute_node_stats(context,
                                                      read_suspended='only')
            for node in compute_nodes:
                mac_to_wake = node['mac_to_wake']
                nova_utils.execute('ether-wake', mac_to_wake, run_as_root=True)
                db.compute_node_update(context, node['compute_id'],
                                       {'suspend_state': 'not suspended'})
                return

    def host_is_empty(self, context, host):
        instances = db.get_instances_stat(context, host)
        if not instances:
            return True
        return False

    def check_is_all_vms_migrated(self, context):
        suspended_nodes = db.get_compute_node_stats(
            context,
            read_suspended='suspending')
        for node in suspended_nodes:
            active_migrations = objects.migration.MigrationList\
                .get_in_progress_by_host_and_node(context,
                                                  node['hypervisor_hostname'],
                                                  node['hypervisor_hostname'])
            if active_migrations:
                LOG.debug('There is some migrations that are in active state')
                # TODO (alexchadin) Make checking that all vms have been migrated.
                return
            else:
                if self.host_is_empty(context, node['hypervisor_hostname']):
                    mac = self.compute_rpc.get_host_mac_addr(
                        context, node['hypervisor_hostname'])
                    db.compute_node_update(context, node['compute_id'],
                                           {'mac_to_wake': mac})
                    self.compute_rpc.suspend_host(context,
                                                  node['hypervisor_hostname'])
                    db.compute_node_update(context, node['compute_id'],
                                           {'suspend_state': 'suspended'})
                else:
                    self.minimizeSD.migrate_all_vms_from_host(
                        context,
                        node['hypervisor_hostname'])