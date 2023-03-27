from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from codecov.commands.base import BaseInteractor
from codecov.commands.exceptions import ValidationError
from codecov.db import sync_to_async
from codecov_auth.models import OwnerProfile


@dataclass
class TermsAgreementInput:
    business_email: Optional[str] = None
    terms_agreement: bool = False


class SaveTermsAgreementInteractor(BaseInteractor):
    def validate(sel, input: TermsAgreementInput):
        if input.terms_agreement is None:
            raise ValidationError("Terms of agreement cannot be null")

    def update_terms_agreement(self, input: TermsAgreementInput):
        owner_profile, _ = OwnerProfile.objects.get_or_create(
            owner=self.current_user,
        )
        owner_profile.terms_agreement = input.terms_agreement
        owner_profile.terms_agreement_at = datetime.now()
        owner_profile.save()

        if input.business_email is not None and input.business_email != "":
            self.current_user.business_email = input.business_email
            self.current_user.save()

    @sync_to_async
    def execute(self, input):
        typed_input = TermsAgreementInput(
            business_email=input.get("businessEmail"),
            terms_agreement=input.get("termsAgreement"),
        )
        self.validate(typed_input)
        return self.update_terms_agreement(typed_input)
