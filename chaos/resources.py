# Copyright (c) 2001-2014, Canal TP and/or its affiliates. All rights reserved.
#
# This file is part of Navitia,
#     the software to build cool stuff with public transport.
#
#     powered by Canal TP (www.canaltp.fr).
# Help us simplify mobility and open public transport:
#     a non ending quest to the responsive locomotion way of traveling!
#
# LICENCE: This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Stay tuned using
# twitter @navitia
# IRC #navitia on freenode
# https://groups.google.com/d/forum/navitia
# www.navitia.io

from flask import g
import flask_restful
from flask_restful import marshal, reqparse
from chaos import models, db, publisher
from jsonschema import validate, ValidationError
from flask.ext.restful import abort
from fields import *
from formats import *
from formats import impact_input_format, channel_input_format, pt_object_type_values,\
    tag_input_format, category_input_format, channel_type_values,\
    property_input_format
from chaos import mapper, exceptions
from chaos import utils, db_helper
import chaos
from sqlalchemy.exc import IntegrityError
import logging
from utils import make_pager, option_value
from chaos.validate_params import validate_client, validate_contributor, validate_navitia, \
    manage_navitia_error, validate_id

__all__ = ['Disruptions', 'Index', 'Severity', 'Cause']


class Index(flask_restful.Resource):

    def get(self):
        url = url_for('disruption', _external=True)
        response = {
            "disruptions": {"href": url},
            "disruption": {"href": url + '/{id}', "templated": True},
            "severities": {"href": url_for('severity', _external=True)},
            "causes": {"href": url_for('cause', _external=True)},
            "channels": {"href": url_for('channel', _external=True)},
            "impactsbyobject": {"href": url_for('impactsbyobject', _external=True)},
            "tags": {"href": url_for('tag', _external=True)},
            "categories": {"href": url_for('category', _external=True)},
            "channeltypes": {"href": url_for('channeltype', _external=True)},
            "status": {"href": url_for('status', _external=True)},
            "traffic_reports": {"href": url_for('trafficreport', _external=True)},
            "properties": {"href": url_for('property', _external=True)}
        }
        return response, 200


class Severity(flask_restful.Resource):

    @validate_client()
    @validate_id()
    def get(self, client, id=None):
        if id:
            return marshal({'severity': models.Severity.get(id, client.id)}, one_severity_fields)
        else:
            response = {'severities': models.Severity.all(client.id), 'meta': {}}
            return marshal(response, severities_fields)

    @validate_client(True)
    def post(self, client):
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('Post severity: %s', json)
        try:
            validate(json, severity_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        severity = models.Severity()
        mapper.fill_from_json(severity, json, mapper.severity_mapping)
        severity.client = client
        try:
            db_helper.manage_wordings(severity, json["wordings"])
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        db.session.add(severity)
        db.session.commit()
        return marshal({'severity': severity}, one_severity_fields), 201

    @validate_client()
    @validate_id(True)
    def put(self, client, id):

        severity = models.Severity.get(id, client.id)
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT severity: %s', json)

        try:
            validate(json, severity_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        mapper.fill_from_json(severity, json, mapper.severity_mapping)
        try:
            db_helper.manage_wordings(severity, json["wordings"])
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        db.session.commit()
        return marshal({'severity': severity}, one_severity_fields), 200

    @validate_client()
    @validate_id(True)
    def delete(self, client, id):

        severity = models.Severity.get(id, client.id)
        severity.is_visible = False
        db.session.commit()
        return None, 204


class Disruptions(flask_restful.Resource):
    def __init__(self):
        self.navitia = None
        self.parsers = {}
        self.parsers["get"] = reqparse.RequestParser()
        parser_get = self.parsers["get"]

        parser_get.add_argument("start_page", type=int, default=1)
        parser_get.add_argument("items_per_page", type=int, default=20)
        parser_get.add_argument("publication_status[]",
                                type=option_value(publication_status_values),
                                action="append",
                                default=publication_status_values)
        parser_get.add_argument("tag[]",
                                type=utils.get_uuid,
                                action="append")
        parser_get.add_argument("current_time", type=utils.get_datetime)
        parser_get.add_argument("uri", type=str)
        parser_get.add_argument(
            "status[]",
            type=option_value(disruption_status_values),
            action="append",
            default=disruption_status_values
        )

    @validate_navitia()
    @validate_contributor()
    @manage_navitia_error()
    @validate_id()
    def get(self, contributor, navitia, id=None):
        self.navitia = navitia
        if id:
            return marshal(
                {'disruption': models.Disruption.get(id, contributor.id)},
                one_disruption_fields
            )
        else:
            args = self.parsers['get'].parse_args()
            page_index = args['start_page']
            if page_index == 0:
                abort(400, message="page_index argument value is not valid")
            items_per_page = args['items_per_page']
            if items_per_page == 0:
                abort(400, message="items_per_page argument value is not valid")
            publication_status = args['publication_status[]']
            tags = args['tag[]']
            uri = args['uri']
            statuses = args['status[]']

            g.current_time = args['current_time']
            result = models.Disruption.all_with_filter(
                page_index=page_index,
                items_per_page=items_per_page,
                contributor_id=contributor.id,
                publication_status=publication_status,
                tags=tags,
                uri=uri,
                statuses=statuses
            )
            response = {'disruptions': result.items, 'meta': make_pager(result, 'disruption')}
            return marshal(response, disruptions_fields)

    @validate_navitia()
    @validate_client(True)
    @manage_navitia_error()
    def post(self, client, navitia):
        self.navitia = navitia
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('POST disruption: %s', json)
        try:
            validate(json, disruptions_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        disruption = models.Disruption()
        mapper.fill_from_json(disruption, json, mapper.disruption_mapping)

        # Use contributor_code present in the json to get contributor_id
        if 'contributor' in json:
            disruption.contributor = models.Contributor.get_or_create(json['contributor'])
        disruption.client = client

        # Add localization present in Json
        try:
            db_helper.manage_pt_object_without_line_section(self.navitia, disruption.localizations, 'localization', json)
        except exceptions.ObjectUnknown, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 404

        # Add all tags present in Json
        db_helper.manage_tags(disruption, json)
        # Add all impacts present in Json
        try:
            db_helper.manage_impacts(disruption, json, self.navitia)
        except exceptions.ObjectUnknown, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 404

        # Add all properties present in Json
        try:
            db_helper.manage_properties(disruption, json)
        except exceptions.ObjectUnknown, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 404

        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 400

        db.session.add(disruption)
        db.session.commit()
        chaos.utils.send_disruption_to_navitia(disruption)
        return marshal({'disruption': disruption}, one_disruption_fields), 201

    @validate_navitia()
    @validate_client()
    @validate_contributor()
    @manage_navitia_error()
    @validate_id(True)
    def put(self, client, contributor, navitia, id):
        self.navitia = navitia
        disruption = models.Disruption.get(id, contributor.id)
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT disruption: %s', json)

        try:
            validate(json, disruptions_input_format)
        except ValidationError, e:
            logging.getLogger(__name__).debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        if disruption.is_published() and 'status' in json\
           and json['status'] == 'draft':
                return marshal(
                    {'error': {'message': 'The current disruption is already\
 published and cannot get back to the \'draft\' status.'}}, error_fields), 409

        mapper.fill_from_json(disruption, json, mapper.disruption_mapping)

        # Use contributor_code present in the json to get contributor_id
        if 'contributor' in json:
            disruption.contributor = models.Contributor.get_or_create(json['contributor'])

        # Add localization present in Json
        try:
            db_helper.manage_pt_object_without_line_section(self.navitia, disruption.localizations, 'localization', json)
        except exceptions.ObjectUnknown, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 404

        # Add/delete tags present/ not present in Json
        db_helper.manage_tags(disruption, json)

        # Add all impacts present in Json
        try:
            db_helper.manage_impacts(disruption, json, self.navitia)
        except exceptions.ObjectUnknown, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 404

        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 400

        # Add all properties present in Json
        try:
            db_helper.manage_properties(disruption, json)
        except exceptions.ObjectUnknown as e:
            db.session.rollback()
            return marshal(
                {'error': {'message': '{}'.format(e.message)}},
                error_fields
                ), 404

        disruption.upgrade_version()
        try:
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            return marshal(
                {'error': {'message': '{}'.format(e.message)}},
                error_fields
                ), 500

        chaos.utils.send_disruption_to_navitia(disruption)
        return marshal({'disruption': disruption}, one_disruption_fields), 200

    @validate_contributor()
    @validate_id(True)
    def delete(self, contributor, id):
        disruption = models.Disruption.get(id, contributor.id)
        disruption.upgrade_version()
        disruption.archive()
        db.session.commit()
        chaos.utils.send_disruption_to_navitia(disruption)
        return None, 204


class Cause(flask_restful.Resource):

    def __init__(self):
        self.parsers = {}
        self.parsers["get"] = reqparse.RequestParser()
        parser_get = self.parsers["get"]
        parser_get.add_argument(
            "category",
            type=utils.get_uuid
        )

    @validate_client()
    @validate_id()
    def get(self, client, id=None):
        args = self.parsers['get'].parse_args()
        category_id = args['category']
        if id:
            response = {'cause': models.Cause.get(id, client.id, category_id)}
            return marshal(response, one_cause_fields)
        else:
            response = {'causes': models.Cause.all(client.id, category_id), 'meta': {}}
            return marshal(response, causes_fields)

    @validate_client(True)
    def post(self, client):
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('Post cause: %s', json)
        try:
            validate(json, cause_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        cause = models.Cause()
        mapper.fill_from_json(cause, json, mapper.cause_mapping)
        cause.client = client
        try:
            db_helper.manage_wordings(cause, json["wordings"])
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        db.session.add(cause)
        db.session.commit()
        return marshal({'cause': cause}, one_cause_fields), 201

    @validate_client()
    @validate_id(True)
    def put(self, client, id):
        cause = models.Cause.get(id, client.id)
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT cause: %s', json)

        try:
            validate(json, cause_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        mapper.fill_from_json(cause, json, mapper.cause_mapping)
        try:
            db_helper.manage_wordings(cause, json["wordings"])
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        db.session.commit()
        return marshal({'cause': cause}, one_cause_fields), 200

    @validate_client()
    @validate_id(True)
    def delete(self, client, id):
        cause = models.Cause.get(id, client.id)
        cause.is_visible = False
        db.session.commit()
        return None, 204


class Tag(flask_restful.Resource):

    @validate_client()
    @validate_id()
    def get(self, client, id=None):
        if id:
            response = {'tag': models.Tag.get(id, client.id)}
            return marshal(response, one_tag_fields)
        else:
            response = {'tags': models.Tag.all(client.id), 'meta': {}}
            return marshal(response, tags_fields)

    @validate_client(True)
    def post(self, client):
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('Post tag: %s', json)
        try:
            validate(json, tag_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        # if an archived tag exists with same name use the same instead of creating a new one.
        archived_tag = models.Tag.get_archived_by_name(json['name'], client.id)
        if archived_tag:
            tag = archived_tag
            tag.client = client
            tag.is_visible = True
        else:
            tag = models.Tag()
            mapper.fill_from_json(tag, json, mapper.tag_mapping)
            tag.client = client
            db.session.add(tag)

        try:
            db.session.commit()
        except IntegrityError, e:
            logging.debug(str(e))
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        return marshal({'tag': tag}, one_tag_fields), 201

    @validate_client()
    @validate_id(True)
    def put(self, client, id):
        tag = models.Tag.get(id, client.id)
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT tag: %s', json)

        try:
            validate(json, tag_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        mapper.fill_from_json(tag, json, mapper.tag_mapping)
        try:
            db.session.commit()
        except IntegrityError, e:
            logging.debug(str(e))
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        return marshal({'tag': tag}, one_tag_fields), 200

    @validate_client()
    @validate_id(True)
    def delete(self, client, id):
        tag = models.Tag.get(id, client.id)
        tag.is_visible = False
        db.session.commit()
        return None, 204


class Category(flask_restful.Resource):

    @validate_client()
    @validate_id()
    def get(self, client, id=None):
        if id:
            response = {'category': models.Category.get(id, client.id)}
            return marshal(response, one_category_fields)
        else:
            response = {'categories': models.Category.all(client.id), 'meta': {}}
            return marshal(response, categories_fields)

    @validate_client(True)
    def post(self, client):
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('Post category: %s', json)
        try:
            validate(json, category_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        # if an archived category exists with same name use the same instead of creating a new one.
        archived_category = models.Category.get_archived_by_name(json['name'], client.id)
        if archived_category:
            category = archived_category
            category.is_visible = True
        else:
            category = models.Category()
            mapper.fill_from_json(category, json, mapper.category_mapping)
            category.client = client
            db.session.add(category)

        try:
            db.session.commit()
        except IntegrityError, e:
            logging.debug(str(e))
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        return marshal({'category': category}, one_category_fields), 201

    @validate_client()
    @validate_id(True)
    def put(self, client, id):
        category = models.Category.get(id, client.id)
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT category: %s', json)

        try:
            validate(json, category_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        mapper.fill_from_json(category, json, mapper.category_mapping)
        try:
            db.session.commit()
        except IntegrityError, e:
            logging.debug(str(e))
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        return marshal({'category': category}, one_category_fields), 200

    @validate_client()
    @validate_id(True)
    def delete(self, client, id):
        category = models.Category.get(id, client.id)
        category.is_visible = False
        db.session.commit()
        return None, 204


class ImpactsByObject(flask_restful.Resource):
    def __init__(self):
        current_datetime = utils.get_current_time()
        default_start_date = current_datetime.replace(hour=0, minute=0, second=0)
        default_end_date = current_datetime.replace(hour=23, minute=59, second=59)
        self.parsers = {}
        self.parsers["get"] = reqparse.RequestParser()
        parser_get = self.parsers["get"]
        parser_get.add_argument("pt_object_type", type=option_value(pt_object_type_values))
        parser_get.add_argument("start_date", type=utils.get_datetime, default=default_start_date)
        parser_get.add_argument("end_date", type=utils.get_datetime, default=default_end_date)
        parser_get.add_argument("uri[]", type=str, action="append")
        self.navitia = None

    @validate_contributor()
    @validate_navitia()
    @manage_navitia_error()
    def get(self, contributor, navitia):
        self.navitia = navitia
        args = self.parsers['get'].parse_args()
        pt_object_type = args['pt_object_type']
        start_date = args['start_date']
        end_date = args['end_date']
        uris = args['uri[]']

        if not pt_object_type and not uris:
                return marshal({'error': {'message': "object type or uri object invalid"}},
                               error_fields), 400
        impacts = models.Impact.all_with_filter(start_date, end_date, pt_object_type, uris, contributor.id)
        result = utils.group_impacts_by_pt_object(impacts, pt_object_type, uris, self.navitia.get_pt_object)
        return marshal({'objects': result}, impacts_by_object_fields)


class Impacts(flask_restful.Resource):
    def __init__(self):
        self.navitia = None
        self.parsers = {}
        self.parsers["get"] = reqparse.RequestParser()
        parser_get = self.parsers["get"]

        parser_get.add_argument("start_page", type=int, default=1)
        parser_get.add_argument("items_per_page", type=int, default=20)

    @validate_contributor()
    @validate_navitia()
    @manage_navitia_error()
    @validate_id()
    def get(self, contributor, disruption_id, navitia, id=None):
        self.navitia = navitia
        if id:
            response = models.Impact.get(id, contributor.id)
            return marshal({'impact': response}, one_impact_fields)
        else:
            if not id_format.match(disruption_id):
                return marshal({'error': {'message': "disruption_id invalid"}},
                           error_fields), 400
            args = self.parsers['get'].parse_args()
            page_index = args['start_page']
            if page_index == 0:
                abort(400, message="page_index argument value is not valid")
            items_per_page = args['items_per_page']
            if items_per_page == 0:
                abort(400, message="items_per_page argument value is not valid")

            result = models.Impact.all(page_index=page_index,
                                       items_per_page=items_per_page,
                                       disruption_id=disruption_id,
                                       contributor_id=contributor.id)
            response = {'impacts': result.items, 'meta': make_pager(result, 'impact', disruption_id=disruption_id)}
            return marshal(response, impacts_fields)

    @validate_client()
    @validate_contributor()
    @validate_navitia()
    @manage_navitia_error()
    def post(self, client, contributor, navitia, disruption_id):
        self.navitia = navitia
        if not id_format.match(disruption_id):
            return marshal({'error': {'message': "id invalid"}},
                           error_fields), 400

        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('POST impcat: %s', json)

        try:
            validate(json, impact_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        disruption = models.Disruption.get(disruption_id, contributor.id)
        try:
            impact = db_helper.create_or_update_impact(disruption, json, self.navitia)
        except exceptions.ObjectUnknown, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 404
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 400

        disruption.upgrade_version()
        db.session.commit()
        chaos.utils.send_disruption_to_navitia(disruption)
        return marshal({'impact': impact}, one_impact_fields), 201

    @validate_client()
    @validate_contributor()
    @validate_navitia()
    @manage_navitia_error()
    @validate_id(True)
    def put(self, client, contributor, navitia, disruption_id, id):
        self.navitia = navitia
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT impact: %s', json)

        try:
            validate(json, impact_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        disruption = models.Disruption.get(disruption_id, contributor.id)
        try:
            impact = db_helper.create_or_update_impact(disruption, json, self.navitia, id)
        except exceptions.ObjectUnknown, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 404
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': '{}'.format(e.message)}}, error_fields), 400
        disruption = models.Disruption.get(disruption_id, contributor.id)
        disruption.upgrade_version()
        db.session.commit()
        chaos.utils.send_disruption_to_navitia(disruption)
        return marshal({'impact': impact}, one_impact_fields), 200

    @validate_contributor()
    @validate_id(True)
    def delete(self, contributor, disruption_id, id):
        impact = models.Impact.get(id, contributor.id)
        impact.archive()
        disruption = models.Disruption.get(disruption_id, contributor.id)
        disruption.upgrade_version()
        db.session.commit()
        chaos.utils.send_disruption_to_navitia(disruption)
        return None, 204


class Channel(flask_restful.Resource):
    @validate_client()
    @validate_id()
    def get(self, client, id=None):
        if id:
            response = {'channel': models.Channel.get(id, client.id)}
            return marshal(response, one_channel_fields)
        else:
            response = {'channels': models.Channel.all(client.id), 'meta': {}}
            return marshal(response, channels_fields)

    @validate_client(True)
    def post(self, client):
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('Post channel: %s', json)
        try:
            validate(json, channel_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        channel = models.Channel()
        mapper.fill_from_json(channel, json, mapper.channel_mapping)
        channel.client = client
        try:
            db_helper.manage_channel_types(channel, json["types"])
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        db.session.add(channel)
        db.session.commit()
        return marshal({'channel': channel}, one_channel_fields), 201

    @validate_client()
    @validate_id(True)
    def put(self, client, id):
        channel = models.Channel.get(id, client.id)
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT channel: %s', json)

        try:
            validate(json, channel_input_format)
        except ValidationError, e:
            logging.debug(str(e))
            # TODO: generate good error messages
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        mapper.fill_from_json(channel, json, mapper.channel_mapping)
        try:
            db_helper.manage_channel_types(channel, json["types"])
        except exceptions.InvalidJson, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400
        db.session.commit()
        return marshal({'channel': channel}, one_channel_fields), 200

    @validate_client()
    @validate_id(True)
    def delete(self, client, id):
        channel = models.Channel.get(id, client.id)
        channel.is_visible = False
        db.session.commit()
        return None, 204


class ChannelType(flask_restful.Resource):
    def get(self):
        return {'channel_types': [type for type in channel_type_values]}, 200


class Status(flask_restful.Resource):
    def get(self):
        return {
            'version': chaos.VERSION,
            'db_pool_status': db.engine.pool.status(),
            'db_version': db.engine.scalar('select version_num from alembic_version;'),
            'navitia_url': current_app.config['NAVITIA_URL'],
            'rabbitmq_info': publisher.info()
        }, 200


class TrafficReport(flask_restful.Resource):
    def __init__(self):
        self.parsers = {}
        self.parsers["get"] = reqparse.RequestParser()
        parser_get = self.parsers["get"]
        parser_get.add_argument("current_time", type=utils.get_datetime, default=utils.get_current_time())
        self.navitia = None

    @validate_contributor()
    @validate_navitia()
    @manage_navitia_error()
    def get(self, contributor, navitia):
        self.navitia = navitia
        args = self.parsers['get'].parse_args()
        g.current_time = args['current_time']
        impacts = models.Impact.traffic_report_filter(contributor.id)
        result = utils.get_traffic_report_objects(impacts, self.navitia)
        return marshal(
            {
                'traffic_reports': [value for key, value in result["traffic_report"].items()],
                'disruptions': result["impacts_used"]
            },
            traffic_reports_marshaler
        ), 200


class Property(flask_restful.Resource):
    def __init__(self):
        self.parsers = {'get': reqparse.RequestParser()}
        self.parsers['get'].add_argument('key').add_argument('type')

    @validate_client()
    @validate_id()
    def get(self, client, id=None):
        args = self.parsers['get'].parse_args()
        key = args['key']
        type = args['type']

        if id:
            property = models.Property.get(client.id, id)

            if property is None:
                return marshal({
                    'error': {'message': 'Property {} not found'.format(id)}
                }, error_fields), 404

            return marshal({'property': property}, one_property_fields)
        else:
            response = {
                'properties': models.Property.all(client.id, key, type)
            }
            return marshal(response, properties_fields)

    @validate_client(True)
    def post(self, client):
        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('POST property: %s', json)

        try:
            validate(json, property_input_format)
        except ValidationError, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        property = models.Property()
        mapper.fill_from_json(property, json, mapper.property_mapping)
        property.client = client
        db.session.add(property)

        try:
            db.session.commit()
        except IntegrityError, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 409

        return marshal({'property': property}, one_property_fields), 201

    @validate_client()
    @validate_id(True)
    def put(self, client, id):
        property = models.Property.get(client.id, id)

        if property is None:
            return marshal({
                'error': {'message': 'Property {} not found'.format(id)}
            }, error_fields), 404

        json = request.get_json(silent=True)
        logging.getLogger(__name__).debug('PUT property: %s', json)

        try:
            validate(json, property_input_format)
        except ValidationError, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 400

        mapper.fill_from_json(property, json, mapper.property_mapping)

        try:
            db.session.commit()
        except IntegrityError, e:
            return marshal({'error': {'message': utils.parse_error(e)}},
                           error_fields), 409

        return marshal({'property': property}, one_property_fields), 200

    @validate_client()
    @validate_id(True)
    def delete(self, client, id):
        property = models.Property.get(client.id, id)

        if property is None:
            return marshal({
                'error': {'message': 'Property {} not found'.format(id)}
            }, error_fields), 404

        can_be_deleted = property.disruptions.filter(
            models.Disruption.status != 'archived',
            models.AssociateDisruptionProperty.disruption_id == models.Disruption.id
        ).count() == 0

        if can_be_deleted:
            db.session.delete(property)
            db.session.commit()
        else:
            return marshal({
                'error': {
                    'message': 'The current {} is linked to at least one disruption\
 and cannot be deleted'.format(property)
                }
            }, error_fields), 409

        return None, 204
