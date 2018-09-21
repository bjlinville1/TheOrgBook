# TODO: migrate most of these serializers to a UI specific serializer module

from collections import OrderedDict
from datetime import datetime, timedelta
import logging

from django.db.models.manager import Manager

from rest_framework.serializers import ListSerializer, SerializerMethodField
from rest_framework.utils.serializer_helpers import ReturnDict
from drf_haystack.serializers import (
    HaystackSerializerMixin, HaystackSerializer, HaystackFacetSerializer,
)

from api_v2.serializers.rest import (
    AddressSerializer,
    AttributeSerializer,
    NameSerializer,
    TopicSerializer,
    CredentialSerializer,
    CredentialTypeSerializer,
    IssuerSerializer,
    CategorySerializer,
    CredentialAddressSerializer,
    CredentialAttributeSerializer,
    CredentialCategorySerializer,
    CredentialNameSerializer,
    CredentialTopicSerializer,
    CredentialTopicExtSerializer,
)

from api_v2.models.Address import Address
from api_v2.models.Attribute import Attribute
from api_v2.models.Category import Category
from api_v2.models.Credential import Credential
from api_v2.models.Name import Name
from api_v2 import utils

from api_v2.search_indexes import CredentialIndex

logger = logging.getLogger(__name__)


class SearchResultsListSerializer(ListSerializer):
    @staticmethod
    def __camelCase(s):
        return s[:1].lower() + s[1:] if s else ""

    def __get_keyName(self, instance):
        searchIndex = instance.searchindex
        model = searchIndex.get_model()
        return self.__camelCase(model.__name__) + "s"

    @property
    def data(self):
        ret = super(ListSerializer, self).data
        return ReturnDict(ret, serializer=self)

    def to_representation(self, data):
        results = OrderedDict()
        iterable = data.all() if isinstance(data, Manager) else data
        for item in iterable:
            searchIndexName = self.__get_keyName(item)
            results.setdefault(searchIndexName, []).append(
                self.child.to_representation(item)
            )

        return results


class CustomCredentialSerializer(CredentialSerializer):
    # topics = CustomTopicSerializer(read_only=True, many=True)

    class Meta(CredentialSerializer.Meta):
        # depth =
        fields = ("id", "effective_date", "inactive", "revoked")


class CustomIssuerSerializer(IssuerSerializer):
    class Meta(IssuerSerializer.Meta):
        fields = ("id", "did", "name", "abbreviation", "email", "url", "has_logo")
        exclude = None


class CustomAddressSerializer(AddressSerializer):
    last_updated = SerializerMethodField()

    class Meta(AddressSerializer.Meta):
        fields = tuple(AddressSerializer.Meta.fields) + ("credential_id", "last_updated")

    def get_last_updated(self, obj):
        return obj.credential.effective_date


class CustomAttributeSerializer(AttributeSerializer):
    last_updated = SerializerMethodField()

    class Meta(AttributeSerializer.Meta):
        fields = ("id", "credential_id", "last_updated", "type", "format", "value")

    def get_last_updated(self, obj):
        return obj.credential.effective_date


class CustomNameSerializer(NameSerializer):
    last_updated = SerializerMethodField()
    issuer = SerializerMethodField()

    class Meta(NameSerializer.Meta):
        fields = ("id", "credential_id", "last_updated", "text", "language", "issuer")

    def get_last_updated(self, obj):
        return obj.credential.effective_date

    def get_issuer(self, obj):
        serializer = CustomIssuerSerializer(
            instance=obj.credential.credential_type.issuer
        )
        return serializer.data


class CustomCategorySerializer(CategorySerializer):
    last_updated = SerializerMethodField()

    class Meta(CategorySerializer.Meta):
        fields = ("id", "credential_id", "last_updated", "type", "value")

    def get_last_updated(self, obj):
        return obj.credential.effective_date


class CustomTopicSerializer(TopicSerializer):
    names = SerializerMethodField()
    addresses = SerializerMethodField()
    attributes = SerializerMethodField()
    categories = SerializerMethodField()

    class Meta(TopicSerializer.Meta):
        depth = 1
        fields = (
            "id",
            "source_id",
            "type",
            "names",
            "addresses",
            "attributes",
            "categories",
        )

    def get_names(self, obj):
        names = Name.objects.filter(
            credential__topic=obj,
            credential__inactive=False,
            credential__revoked=False,
        )
        serializer = CustomNameSerializer(instance=names, many=True)
        return serializer.data

    def get_addresses(self, obj):
        addresses = Address.objects.filter(
            credential__topic=obj,
            credential__inactive=False,
            credential__revoked=False,
        )
        serializer = CustomAddressSerializer(instance=addresses, many=True)
        return serializer.data

    def get_attributes(self, obj):
        attributes = Attribute.objects.filter(
            credential__topic=obj,
            credential__inactive=False,
            credential__revoked=False,
        )
        serializer = CustomAttributeSerializer(instance=attributes, many=True)
        return serializer.data

    def get_categories(self, obj):
        categories = Category.objects.filter(
            credential__topic=obj,
            credential__inactive=False,
            credential__revoked=False,
        )
        serializer = CustomCategorySerializer(instance=categories, many=True)
        return serializer.data


class CredentialSearchSerializer(HaystackSerializerMixin, CredentialSerializer):
    addresses = CredentialAddressSerializer(many=True)
    attributes = CredentialAttributeSerializer(many=True)
    categories = CredentialCategorySerializer(many=True)
    credential_type = CredentialTypeSerializer()
    names = CredentialNameSerializer(many=True)
    topic = CredentialTopicSerializer()

    class Meta(CredentialSerializer.Meta):
        fields = (
            "id", "create_timestamp", "update_timestamp",
            "credential_type", "effective_date",
            "addresses", "attributes", "categories", "names",
            "inactive", "revoked", "topic",
        )
        search_fields = (
            "category", "location", "name",
            "effective_date", "inactive", "revoked",
            "topic_id", "topic_type", "topic_source_id",
            "credential_type_id", "issuer_id",
        )


class CredentialTopicSearchSerializer(CredentialSearchSerializer):
    """
    Return credentials with addresses and categories removed, but
    added for the related topic instead
    """
    topic = CredentialTopicExtSerializer()

    class Meta(CredentialSearchSerializer.Meta):
        fields = (
            "id", "create_timestamp", "update_timestamp",
            "credential_type", "effective_date",
            "names",
            "inactive", "revoked", "topic",
        )


class CredentialFacetSerializer(HaystackFacetSerializer):
    serialize_objects = True
    class Meta:
        index_classes = [CredentialIndex]
        fields = [
            "effective_date", "topic_type", "issuer_id",
            # "credential_type_id",
        ]
        field_options = {
            "topic_type": {},
            "issuer_id": {},
# date faceting isn't working, needs to use Solr range faceting
# https://github.com/django-haystack/django-haystack/issues/1572
#             "effective_date": {
#                 "start_date": datetime.now() - timedelta(days=50000),
#                 "end_date": datetime.now(),
#                 "gap_by": "month",
#                 "gap_amount": 3
#             },
        }

    def get_objects(self, instance):
        """
        Overriding default behaviour to use more standard pagination info
        """
        view = self.context["view"]
        queryset = self.context["objects"]

        page = view.paginate_queryset(queryset)
        if page is not None:
            serializer = view.get_facet_objects_serializer(page, many=True)
            response = view.paginator.get_paginated_response(serializer.data)
            return response.data # unwrap value

        return super(CredentialFacetSerializer, self).get_objects()
