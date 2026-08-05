# -*- coding: utf-8 -*-
"""V76 requirements."""
import ast
import io
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def function_source(source, name):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError("function %s not found" % name)


class FrontOfQueueNotice(unittest.TestCase):
    def test_queue_row_stores_the_notice_id(self):
        self.assertIn("front_notice_outbox_id = Column(Integer)", read("common/models.py"))

    def test_startup_ddl_adds_the_column(self):
        self.assertIn(
            "drivers_queue ADD COLUMN IF NOT EXISTS front_notice_outbox_id",
            read("common/db_migrate.py"),
        )

    def test_migration_exists(self):
        migration = read("migrations/versions/0041_front_notice_tracking.py")
        self.assertIn('down_revision = "0040_offer_notice_tracking"', migration)

    def test_notice_is_tracked(self):
        source = function_source(read("bot/queue_service.py"), "_notify_fronts")
        self.assertIn("front_notice_outbox_id = _vk.send_tracked_message", source)

    def test_notice_is_removed_when_driver_is_not_front(self):
        source = function_source(read("bot/queue_service.py"), "_notify_fronts")
        self.assertEqual(source.count("_clear_front_notice(session, e)"), 3)
        clear = function_source(read("bot/queue_service.py"), "_clear_front_notice")
        self.assertIn("outbox_service.cancel_or_delete", clear)
        self.assertIn("entry.front_notified = False", clear)
        self.assertIn("entry.front_notice_outbox_id = None", clear)

    def test_busy_driver_loses_the_notice(self):
        source = function_source(read("bot/queue_service.py"), "_notify_fronts")
        marker = "if drv and _driver_has_active_work(session, drv.id):"
        self.assertIn(marker, source)
        after = source.split(marker, 1)[1]
        self.assertIn("_clear_front_notice(session, e)", after.split("continue", 1)[0])


class DispatcherRequisites(unittest.TestCase):
    def test_single_details_button_in_the_menu(self):
        menu = function_source(read("bot/keyboards.py"), "dispatcher_menu")
        self.assertEqual(menu.count('"disp_income"'), 1)
        self.assertIn("Мои сведения", menu)
        self.assertNotIn("Мои доходы", menu)
        self.assertNotIn('"disp_payment"', menu)

    def test_details_screen_has_its_own_menu(self):
        info = function_source(read("bot/keyboards.py"), "dispatcher_info_menu")
        self.assertIn('"cmd": "disp_payment"', info)
        self.assertIn("Изменить реквизиты", info)
        self.assertIn('"cmd": "start"', info)
        self.assertIn("Назад в главное меню", info)

    def test_details_screen_shows_income_and_requisites(self):
        source = function_source(read("bot/handlers.py"), "disp_show_income")
        self.assertIn("dispatcher_income_text(session, user.id)", source)
        self.assertIn("_payment_details_ready(user)", source)
        self.assertIn("_payment_details_text(user)", source)
        self.assertIn("kb.dispatcher_info_menu()", source)

    def test_wizard_is_routed_for_dispatchers(self):
        handlers = read("bot/handlers.py")
        router = function_source(handlers, "handle_dispatcher")
        self.assertIn("_PAYMENT_STATES", router)
        self.assertIn("_handle_payment_wizard(session, user, state, text, payload)", router)
        wizard = function_source(handlers, "_handle_payment_wizard")
        for step in (
            "driver_payment_method(session, user, payload.get(\"type\"))",
            "driver_payment_phone(session, user, text)",
            "driver_payment_card(session, user, text)",
            "driver_payment_bank(session, user, text)",
            "driver_payment_recipient(session, user, text)",
            "driver_payment_cancel(session, user)",
        ):
            self.assertIn(step, wizard)

    def test_command_is_routed(self):
        handlers = read("bot/handlers.py")
        self.assertIn('if cmd == "disp_payment":', handlers)
        self.assertIn("return disp_payment_details(session, user)", handlers)

    def test_dispatcher_uses_the_driver_wizard(self):
        source = function_source(read("bot/handlers.py"), "disp_payment_details")
        self.assertIn("driver_payment_start(session, user, dispatcher=True)", source)

    def test_draft_keeps_the_dispatcher_flag(self):
        start = function_source(read("bot/handlers.py"), "driver_payment_start")
        self.assertIn("dispatcher: bool = False", start)
        self.assertIn('{"dispatcher": True} if dispatcher else {}', start)
        method = function_source(read("bot/handlers.py"), "driver_payment_method")
        self.assertIn('draft["dispatcher"] = True', method)

    def test_saving_returns_to_dispatcher_menu(self):
        save = function_source(read("bot/handlers.py"), "driver_payment_recipient")
        self.assertIn('if draft.get("dispatcher"):', save)
        self.assertIn("disp_show_income(session, user)", save)
        self.assertIn("States.DISP_MENU", save)

    def test_driver_flow_is_unchanged(self):
        save = function_source(read("bot/handlers.py"), "driver_payment_recipient")
        self.assertIn("user.show_payment_details = False", save)
        self.assertIn("kb.driver_settings_keyboard(False, user.driver_gender)", save)

    def test_cancel_returns_dispatcher_to_their_menu(self):
        cancel = function_source(read("bot/handlers.py"), "driver_payment_cancel")
        self.assertIn('.get("dispatcher")', cancel)
        self.assertIn("disp_show_income(session, user)", cancel)
        self.assertIn("States.DISP_MENU", cancel)


class WeeklyReport(unittest.TestCase):
    def test_threshold_constant(self):
        self.assertIn("MIN_WEEKLY_ORDERS = 2", read("bot/dispatcher_report_service.py"))

    def test_orders_are_counted_by_dispatcher_role(self):
        source = function_source(
            read("bot/dispatcher_report_service.py"), "dispatcher_orders_count"
        )
        self.assertIn("Order.dispatcher_id == dispatcher_id", source)
        self.assertIn("Order.created_at >= start", source)

    def test_report_only_for_active_dispatchers(self):
        source = function_source(
            read("bot/dispatcher_report_service.py"), "send_due_weekly_reports"
        )
        self.assertIn("orders_made >= MIN_WEEKLY_ORDERS", source)

    def test_drivers_get_one_message_per_dispatcher(self):
        source = function_source(
            read("bot/dispatcher_report_service.py"), "send_due_weekly_reports"
        )
        self.assertIn("weekly_driver_debt:", source)
        self.assertIn("driver_debt_notice_text(", source)
        self.assertIn("if not amount or amount <= 0:", source)

    def test_driver_notice_contains_amount_and_requisites(self):
        source = function_source(
            read("bot/dispatcher_report_service.py"), "driver_debt_notice_text"
        )
        self.assertIn("payment_details_text(dispatcher)", source)
        self.assertIn("dispatcher.vk_id", source)

    def test_requisites_render_like_driver_ones(self):
        source = function_source(
            read("bot/dispatcher_report_service.py"), "payment_details_text"
        )
        self.assertIn('user.payment_type == "card"', source)
        self.assertIn("user.payment_bank", source)

    def test_driver_notices_are_deduplicated(self):
        source = function_source(
            read("bot/dispatcher_report_service.py"), "send_due_weekly_reports"
        )
        self.assertIn("ProcessedEvent(event_key=driver_key)", source)


class DriverFoundNotice(unittest.TestCase):
    def test_old_wording_is_gone(self):
        self.assertNotIn(
            "Водитель указывает время, через сколько прибудет.",
            read("bot/order_service.py"),
        )

    def test_new_wording(self):
        source = function_source(read("bot/order_service.py"), "notify_driver_found")
        self.assertIn(
            "Нашёлся водитель, он указывает время прибытия и выезжает к вам.",
            source,
        )
        self.assertIn("send_tracked_message", source)
        self.assertIn("_is_dispatcher_order(order)", source)

    def test_sent_after_the_driver_accepts(self):
        accept = function_source(read("bot/handlers.py"), "driver_accept")
        self.assertIn("order_service.notify_driver_found(session, order)", accept)

    def test_notice_is_still_cleaned_up_on_reoffer(self):
        clear = function_source(read("bot/order_service.py"), "clear_offer_notice")
        self.assertIn("offer_notice_outbox_id", clear)


if __name__ == "__main__":
    unittest.main()
