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

from oslo_config import cfg

from nova import exception
from nova.api.openstack import common
from nova.compute import api as compute_api
from nova.loadbalancer import utils as lb_utils
from oslo_utils import importutils
from nova.scheduler import filters


CONF = cfg.CONF
CONF.import_opt('scheduler_host_manager', 'nova.scheduler.driver')
CONF.import_opt('scheduler_default_filters', 'nova.scheduler.host_manager')


class BaseBalancer(object):

    def __init__(self, *args, **kwargs):
        super(BaseBalancer, self).__init__(*args, **kwargs)
        self.host_manager = importutils.import_object(
            CONF.scheduler_host_manager)
        self.filter_handler = filters.HostFilterHandler()
        self.compute_api = compute_api.API()

    def balance(self, context, **kwargs):
        pass

    def filter_hosts(self, context, chosen_instance, nodes, host=None):
        filter_properties = lb_utils.build_filter_properties(context,
                                                             chosen_instance,
                                                             nodes)
        classes = self.host_manager.choose_host_filters(
            CONF.scheduler_default_filters)
        # If hypervisor_hostname is set, query returns only specified host.
        hosts = self.host_manager.get_all_host_states(context,
                                                      hypervisor_hostname=host)
        filtered = self.filter_handler.get_filtered_objects(classes,
                                                            hosts,
                                                            filter_properties)
        return filtered, filter_properties

    def migrate(self, context, instance_uuid, hostname=None,
                cold_migration=None):
        if not cold_migration:
            instance = lb_utils.get_instance_object(context,
                                                    instance_uuid)
            self.compute_api.live_migrate(lb_utils.get_context(), instance,
                                          False, False, hostname)
        else:
            instance = common.get_instance(self.compute_api,
                                           lb_utils.get_context(),
                                           instance_uuid)
            try:
                self.compute_api.resize(lb_utils.get_context(), instance)
            except exception.NoValidHost:
                return False
            return True

    def confirm_migration(self, context, instance_uuid):
        instance = self.compute_api.get(lb_utils.get_context(), instance_uuid,
                                        want_objects=True)
        self.compute_api.confirm_resize(lb_utils.get_context(), instance)
