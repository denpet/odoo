import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

patch(PaymentScreen.prototype, {
    _roomChargeAlert(body) {
        this.dialog.add(AlertDialog, { title: _t("Charge to Room"), body });
    },

    _roomChargeDefaultFolioId(order) {
        if (order.room_charge_folio_ref) {
            return order.room_charge_folio_ref;
        }
        // For a refund, suggest the folio of the original order.
        const refunded = order.lines.find((l) => l.refunded_orderline_id)?.refunded_orderline_id;
        return refunded?.order_id?.room_charge_folio_ref || false;
    },

    async addNewPaymentLine(paymentMethod) {
        const order = this.currentOrder;
        const hasRoomCharge = this.paymentLines.some((l) => l.payment_method_id?.is_room_charge);

        if (!paymentMethod.is_room_charge) {
            if (hasRoomCharge) {
                this._roomChargeAlert(
                    _t("Charge to Room must be the only payment. Remove it first to pay another way.")
                );
                return false;
            }
            return super.addNewPaymentLine(...arguments);
        }

        if (this.paymentLines.length) {
            this._roomChargeAlert(
                _t("Charge to Room must be the only payment. Remove the other payments first.")
            );
            return false;
        }
        if (order.isToInvoice()) {
            this._roomChargeAlert(
                _t("Room charges are invoiced with the folio. Turn off Invoice for this order.")
            );
            return false;
        }

        let folios;
        try {
            folios = await this.pos.data.call("hotel.folio", "get_room_charge_folios", [
                this.pos.company.id,
            ]);
        } catch {
            this._roomChargeAlert(
                _t("Couldn't load the checked-in guests. Check the connection and try again.")
            );
            return false;
        }
        if (!folios.length) {
            this._roomChargeAlert(_t("No guests are checked in right now."));
            return false;
        }

        const defaultId = this._roomChargeDefaultFolioId(order);
        const folio = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Charge to which room?"),
            list: folios.map((f) => ({
                id: f.id,
                label: f.label,
                isSelected: f.id === defaultId,
                item: f,
            })),
        });
        if (!folio) {
            return false;
        }
        order.update({ room_charge_folio_ref: folio.id, room_charge_label: folio.label });
        return super.addNewPaymentLine(...arguments);
    },
});
