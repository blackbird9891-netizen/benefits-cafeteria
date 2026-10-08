"""Наполнение базы демонстрационными данными.

Все данные вымышлены: сотрудники, суммы, организации созданы для демонстрации
и не относятся к реальным лицам или компаниям.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import points as pts
from app.core.security import hash_password
from app.database import Base, SessionLocal, engine
from app.models import (
    Anomaly,
    Campaign,
    CatalogItem,
    DmsPolicy,
    ItemType,
    NewsPost,
    Order,
    OrderApproval,
    OrderStatus,
    PlatformSetting,
    PromoBatch,
    Role,
    Section,
    Survey,
    Ticket,
    User,
)

SECTIONS = [
    ("common", "Общие предложения", "◆", 1),
    ("health", "Моё здоровье", "✚", 2),
    ("learn", "Обучение", "✎", 3),
    ("rest", "Отдых и спорт", "❧", 4),
    ("family", "Семья и дети", "☗", 5),
    ("life", "Баланс и время", "◷", 6),
]

USERS = [
    dict(email="a.drozdiuk@corp.example", password="demo1234", full_name="Дроздюк А. В.",
         position="Руководитель клиентского сервиса", grade="G12", department="Клиентский сервис",
         role=Role.EMPLOYEE.value, hired_at=date(2021, 3, 15), birth_date=date(1989, 2, 11),
         city="Петрозаводск", sex="М", phone="+7 921 ***-46-17", chief="Соколова И. П.",
         vacation_left=4, budget=8000),
    dict(email="i.sokolova@corp.example", password="hr1234", full_name="Соколова И. П.",
         position="Директор по персоналу", grade="G15", department="HR",
         role=Role.HR.value, hired_at=date(2018, 6, 1), birth_date=date(1984, 9, 23),
         city="Москва", sex="Ж", phone="+7 916 ***-11-02", chief="—",
         vacation_left=12, budget=11000),
    dict(email="d.kim@corp.example", password="demo1234", full_name="Ким Д. С.",
         position="Инженер-конструктор", grade="G9", department="Проектирование",
         role=Role.EMPLOYEE.value, hired_at=date(2023, 9, 4), birth_date=date(1995, 12, 2),
         city="Казань", sex="М", phone="+7 917 ***-77-31", chief="Орлов В. Н.",
         vacation_left=0, budget=5000),
    dict(email="e.nazarova@corp.example", password="demo1234", full_name="Назарова Е. А.",
         position="Менеджер проектов", grade="G11", department="Проектный офис",
         role=Role.DECREE.value, hired_at=date(2019, 11, 18), birth_date=date(1991, 5, 30),
         city="Москва", sex="Ж", phone="+7 926 ***-04-55", chief="Соколова И. П.",
         vacation_left=7, budget=6500),
    dict(email="v.orlov@corp.example", password="demo1234", full_name="Орлов В. Н.",
         position="Технический директор", grade="G17", department="Дирекция",
         role=Role.VIP.value, hired_at=date(2016, 2, 8), birth_date=date(1978, 7, 14),
         city="Москва", sex="М", phone="+7 903 ***-19-88", chief="—",
         vacation_left=9, budget=0),
    dict(email="p.gavrilov@corp.example", password="demo1234", full_name="Гаврилов П. И.",
         position="Специалист по снабжению", grade="", department="Снабжение",
         role=Role.EXCLUDED.value, hired_at=date(2026, 9, 22), birth_date=date(1993, 3, 19),
         city="Тверь", sex="М", phone="+7 920 ***-63-40", chief="Орлов В. Н.",
         vacation_left=0, budget=0),
    dict(email="s.belov@corp.example", password="admin1234", full_name="Белов С. А.",
         position="Администратор системы", grade="G13", department="ИТ",
         role=Role.ADMIN.value, hired_at=date(2020, 4, 6), birth_date=date(1987, 11, 5),
         city="Москва", sex="М", phone="+7 905 ***-28-14", chief="Орлов В. Н.",
         vacation_left=5, budget=9000),
]

ITEMS = [
    # section, category, title, price, type, supplier, desc, cond, icon, extra
    ("common", "Сертификаты", "Подарочная карта «Озон»", 3000, ItemType.GIFT.value, "Giftery",
     "Электронный сертификат на любые товары маркетплейса. Код приходит на корпоративную почту в течение 15 минут.",
     "Срок действия кода 12 месяцев. Отмена заказа после выдачи кода невозможна.", "▣",
     dict(low_at=20, limit_count=2, limit_period="месяц", files=["Условия_Giftery.pdf"])),
    ("common", "Сертификаты", "Виртуальная банковская карта", 5000, ItemType.CARD.value, "Банк-партнёр",
     "Предоплаченная виртуальная карта. Номер и CVV направляются на корпоративную почту.",
     "Карта действует 12 месяцев. Возврат баллов после выпуска не производится.", "▭",
     dict(limit_count=1, limit_period="квартал")),
    ("common", "Техника", "Компенсация рабочего места", 8000, ItemType.DOCUMENT.value, "Внутренняя программа",
     "Компенсация покупки монитора, кресла или стола для домашнего рабочего места по чеку.",
     "Требуется загрузка чека. Проверка HR до 3 рабочих дней.", "▤", dict(needs_doc=True)),
    ("common", "Техника", "Беспроводная гарнитура", 4500, ItemType.PHYSICAL.value, "Склад компании",
     "Гарнитура с активным шумоподавлением. Доставка на рабочее место или по адресу сотрудника.",
     "Срок доставки 5–7 рабочих дней. Возврат возможен до передачи в доставку.", "◗",
     dict(stock=12, low_at=5)),

    ("health", "ДМС", "Стоматология расширенная", 7000, ItemType.DMS.value, "СК «Ресо-Гарантия»",
     "Расширение базовой программы: лечение, гигиена, пломбы, лимит 60 000 ₽ в год.",
     "Подключается в окно выбора, действует до окончания основного полиса.", "✚",
     dict(files=["Программа_стоматология.pdf"])),
    ("health", "ДМС", "Углублённая диагностика", 6000, ItemType.DMS.value, "СК «Ресо-Гарантия»",
     "Чек-ап: лабораторная диагностика, УЗИ, консультации профильных специалистов, раз в год.",
     "Запись через приложение страховщика после активации.", "✚", dict()),
    ("health", "ДМС", "Госпитализация", 9000, ItemType.DMS.value, "СК «Ресо-Гарантия»",
     "Экстренная и плановая госпитализация в клиниках-партнёрах.",
     "Действует с 15-го дня после подключения.", "✚", dict()),
    ("health", "Здоровье", "Консультация психолога", 2200, ItemType.SLOT.value, "Сервис «Ясно»",
     "Онлайн-сессия 50 минут с выбором специалиста и времени.",
     "Перенос не позднее чем за 24 часа до сессии.", "◔", dict(has_slots=True)),
    ("health", "Здоровье", "Вакцинация от гриппа", 1200, ItemType.SLOT.value, "Клиника «Медси»",
     "Вакцинация в выездном пункте на территории офиса или в клинике по выбору.",
     "Сезонная позиция, доступна до 30 ноября.", "◔",
     dict(has_slots=True, limit_count=1, limit_period="год")),

    ("learn", "Внешнее обучение", "Курс «Продуктовая аналитика»", 12000, ItemType.EDUCATION.value,
     "Внешняя школа", "Онлайн-курс 10 недель с проверкой домашних заданий и итоговым проектом.",
     "Лимит мест на поток. Доступ направляется на почту в течение 2 рабочих дней.", "✎",
     dict(seats=3, cap_amount=15000)),
    ("learn", "Внешнее обучение", "Сертификация PMP", 14000, ItemType.EDUCATION.value, "Учебный центр",
     "Подготовка и оплата экзамена на сертификат PMP.",
     "Предел компенсации 15 000 баллов. Требуется согласование руководителя.", "✎",
     dict(cap_amount=15000, approvals=["Руководитель"])),
    ("learn", "Языки", "Английский язык, группа", 6500, ItemType.EDUCATION.value, "Внутренняя программа",
     "Групповые занятия дважды в неделю, уровни A2–C1, корпоративный преподаватель.",
     "Запись в начале семестра, группы до 8 человек.", "✎", dict(seats=6)),
    ("learn", "Конференции", "Участие в отраслевой конференции", 9500, ItemType.DOCUMENT.value,
     "Внешний организатор", "Оплата участия в профильной конференции на территории РФ.",
     "Предел суммы 10 000 баллов. Требуется программа мероприятия и согласование руководителя.", "▤",
     dict(needs_doc=True, cap_amount=10000, approvals=["Руководитель"])),

    ("rest", "Спорт", "Фитнес, полугодовой абонемент", 11000, ItemType.GIFT.value, "Сеть клубов",
     "Абонемент в сеть клубов по месту жительства, бассейн и групповые занятия включены.",
     "Промокод активируется в приложении клуба, в ротацию не возвращается.", "▣", dict(low_at=10)),
    ("rest", "Проживание", "База отдыха «Сосновый бор»", 9000, ItemType.STAY.value, "База отдыха",
     "Домик на 4 человека, две спальни, терраса, баня по записи.",
     "Минимум 2 суток, бронирование не позднее 7 дней до заезда.", "❧", dict()),
    ("rest", "Путешествия", "Туристический сертификат", 10000, ItemType.GIFT.value, "Туроператор",
     "Сертификат на путешествия по России, суммируется с личными средствами.",
     "Срок действия 12 месяцев. Отмена после выдачи невозможна.", "▣", dict(low_at=8)),

    ("family", "Дети", "Компенсация детского сада", 7500, ItemType.DOCUMENT.value, "Внутренняя программа",
     "Частичная компенсация оплаты детского сада по платёжным документам.",
     "Загрузка квитанции за месяц, проверка HR, выплата к следующей зарплате.", "▤",
     dict(needs_doc=True)),
    ("family", "Дети", "Детский лагерь, смена", 13000, ItemType.DOCUMENT.value, "Партнёр программы",
     "Оплата смены в загородном лагере для детей сотрудников 7–15 лет.",
     "Заявка до 1 мая. Требуется подтверждение возраста ребёнка.", "▤",
     dict(needs_doc=True, limit_count=1, limit_period="год")),
    ("family", "Дети", "Кружки и секции", 4000, ItemType.DOCUMENT.value, "Внутренняя программа",
     "Компенсация занятий ребёнка в секции или кружке по чеку.",
     "Не более двух компенсаций в год на одного ребёнка.", "▤",
     dict(needs_doc=True, limit_count=2, limit_period="год")),
    ("family", "ДМС", "ДМС для члена семьи", 0, ItemType.DMS_FAMILY.value, "СК «Ресо-Гарантия»",
     "Подключение супруга или ребёнка к программе ДМС. Стоимость рассчитывается по возрасту.",
     "Возраст застрахованного от 1 года до 65 лет. Данные проверяются страховщиком.", "✚", dict()),

    ("life", "Время", "День дополнительного отпуска", 5500, ItemType.VACATION.value, "Кадровая служба",
     "Дополнительный оплачиваемый день отпуска сверх основного.",
     "Обязательное согласование руководителя и кадровой службы. Недоступно при неотгулянном отпуске.", "◷",
     dict(approvals=["Руководитель", "Кадровая служба"], limit_count=3, limit_period="год")),
    ("life", "Время", "Гибкий график", 0, ItemType.FLEX.value, "Внутренняя программа",
     "Сдвиг начала рабочего дня в пределах двух часов, нефинансовая льгота.",
     "Активируется без списания баллов, отражается в профиле. Согласование руководителя.", "◷",
     dict(approvals=["Руководитель"])),
    ("life", "Развитие", "Сессия с карьерным коучем", 3800, ItemType.SLOT.value, "Внешний коуч",
     "Индивидуальная сессия 60 минут: цели, план развития, подготовка к оценке.",
     "Выбор свободной даты, перенос за 24 часа.", "◔", dict(has_slots=True)),
]

SETTINGS = [
    ("transfer_fee", "25", "int", "Комиссия перевода баллов, %"),
    ("transfer_min", "500", "int", "Минимальная сумма перевода"),
    ("charity_match", "2", "int", "Множитель софинансирования благотворительности"),
    ("point_rub", "1", "int", "Стоимость балла в рублях"),
    ("burn_months", "12", "int", "Срок сгорания баллов, месяцев"),
    ("manual_cap", "20000", "int", "Потолок ручного начисления"),
    ("support_sla", "24", "int", "Срок ответа поддержки, часов"),
    ("window_mode", "restrict", "str", "Режим окна выбора: restrict или inform"),
    ("module_lottery", "1", "bool", "Раздел «Лотерея»"),
    ("module_team_pool", "1", "bool", "Раздел «Командные сборы»"),
    ("module_transfer", "1", "bool", "Раздел «Перевод баллов»"),
    ("module_charity", "1", "bool", "Раздел «Благотворительность»"),
    ("module_social", "0", "bool", "Раздел «Социальные проекты»"),
    ("module_starter", "1", "bool", "Стартовый пакет"),
]


def run_seed(force: bool = False) -> None:
    Base.metadata.create_all(engine)
    db: Session = SessionLocal()
    try:
        if db.scalar(select(User).limit(1)) and not force:
            print("База уже заполнена, пропускаю.")
            return

        sections = {}
        for code, title, icon, order in SECTIONS:
            s = Section(code=code, title=title, icon=icon, sort_order=order)
            db.add(s)
            sections[code] = s
        db.flush()

        items_by_title = {}
        for sec, cat, title, price, itype, supplier, desc, cond, icon, extra in ITEMS:
            item = CatalogItem(
                section_id=sections[sec].id, category=cat, title=title, price=price,
                item_type=itype, supplier=supplier, description=desc, conditions=cond,
                icon=icon, **extra,
            )
            db.add(item)
            items_by_title[title] = item
        db.flush()

        for key, value, vtype, title in SETTINGS:
            db.add(PlatformSetting(key=key, value=value, value_type=vtype, title=title))

        users = {}
        for data in USERS:
            password = data.pop("password")
            u = User(**data, hashed_password=hash_password(password))
            db.add(u)
            users[u.email] = u
            data["password"] = password
        db.flush()

        # --- начисления (раздел 4.4 ТЗ) ---
        for u in users.values():
            if u.role in (Role.VIP.value, Role.DECREE.value, Role.EXCLUDED.value):
                continue
            pts.grant(db, u, 5000, "Базовое начисление за 2026 год",
                      granted_at=date(2026, 1, 15), burn_at=date(2027, 1, 15))

        for u in users.values():
            if u.role == Role.EXCLUDED.value or not u.hired_at:
                continue
            years = (date.today() - u.hired_at).days // 365
            if years > 0:
                pts.grant(db, u, years * 500, f"Стаж: {years} полных лет",
                          burnable=False, granted_at=date(2026, u.hired_at.month, u.hired_at.day))

        me = users["a.drozdiuk@corp.example"]
        pts.grant(db, me, 1500, "День рождения", granted_at=date(2026, 2, 11), burn_at=date(2027, 2, 11))
        pts.grant(db, me, 1200, "23 Февраля", granted_at=date(2026, 2, 23), burn_at=date(2027, 2, 23))
        pts.grant(db, me, 1000, "День рождения ребёнка", granted_at=date(2026, 4, 18), burn_at=date(2027, 4, 18))
        pts.grant(db, me, 4000, "Признание за проект «Витрина поставщиков»",
                  burnable=False, granted_at=date(2026, 7, 1), granted_by="Соколова И. П.")
        pts.grant(db, me, 2000, "День строителя", granted_at=date(2026, 8, 9), burn_at=date(2026, 11, 9))
        pts.grant(db, me, 2500, "День компании", granted_at=date(2026, 9, 5), burn_at=date(2026, 12, 5))
        pts.grant(db, users["d.kim@corp.example"], 1500, "День рождения",
                  granted_at=date(2026, 12, 2), burn_at=date(2027, 12, 2))
        pts.grant(db, users["e.nazarova@corp.example"], 1200, "8 Марта",
                  granted_at=date(2026, 3, 8), burn_at=date(2027, 3, 8))

        # --- партии промокодов ---
        db.add(PromoBatch(item_id=items_by_title["Подарочная карта «Озон»"].id,
                          total=60, used=12, expires_at=date(2027, 9, 30)))
        db.add(PromoBatch(item_id=items_by_title["Фитнес, полугодовой абонемент"].id,
                          total=30, used=23, expires_at=date(2027, 3, 31)))
        db.add(PromoBatch(item_id=items_by_title["Туристический сертификат"].id,
                          total=40, used=15, expires_at=date(2027, 6, 30)))

        # --- ДМС ---
        for u in users.values():
            db.add(DmsPolicy(user_id=u.id, base_program="Базовая программа «Оптима»",
                             policy_to=date(2027, 3, 31), extensions=[]))

        # --- кампания ---
        db.add(Campaign(title="Окно выбора IV квартал 2026",
                        date_from=date(2026, 9, 15), date_to=date(2026, 12, 20),
                        is_open=True, segments=["all"]))

        # --- история заказов ---
        def make_order(user, title, status, days_ago, code=None, options=None):
            item = items_by_title[title]
            order = Order(
                public_id=f"ORD-{100400 + days_ago}", user_id=user.id, item_id=item.id,
                price=item.price, status=status, code=code, options=options or {},
                created_at=datetime.now() - timedelta(days=days_ago),
            )
            db.add(order)
            db.flush()
            if item.approvals:
                for idx, approver in enumerate(item.approvals):
                    db.add(OrderApproval(order_id=order.id, approver=approver, sort_order=idx))
            pts.spend(db, user, item.price, f"Заказ {order.public_id}")
            return order

        make_order(me, "Подарочная карта «Озон»", OrderStatus.DONE.value, 120, code="OZN-4K7P-22LM")
        make_order(me, "Консультация психолога", OrderStatus.DONE.value, 78,
                   options={"slot": "28.07, 18:00"})
        make_order(me, "День дополнительного отпуска", OrderStatus.APPROVE.value, 9)
        make_order(users["d.kim@corp.example"], "Английский язык, группа", OrderStatus.WORK.value, 25)

        # --- обращения ---
        db.add(Ticket(public_id="SUP-2041", user_id=me.id, topic="Сертификат не пришёл",
                      body="Оформил карту «Озон», код на почту не поступил.",
                      status="closed", answer="Код отправлен повторно в тот же день."))
        db.add(Ticket(public_id="SUP-2088", user_id=users["d.kim@corp.example"].id,
                      topic="Вопрос по лимиту",
                      body="Можно ли купить второй курс в этом году?", status="open"))

        # --- новости и опросы ---
        db.add(NewsPost(title="Окно выбора открыто до 20 декабря", pinned=True,
                        body="Распределите баллы до закрытия окна. После 20 декабря изменение набора потребует заявки в HR."))
        db.add(NewsPost(title="Новый партнёр: сеть клубов «Атлет»",
                        body="Добавлен полугодовой абонемент. Количество промокодов ограничено."))
        db.add(Survey(title="Какие льготы добавить в 2027 году",
                      question="Что для вас важнее всего?",
                      options=["Расширение ДМС", "Обучение и сертификации", "Спорт и фитнес",
                               "Компенсация жилья"],
                      votes=[41, 33, 52, 28]))

        # --- аномалия ---
        db.add(Anomaly(rule="Ручное начисление свыше потолка", actor="Соколова И. П.",
                       detail="Начислено 18 000 баллов трём сотрудникам в нерабочее время"))

        pts.write_audit(db, "Система", "Инициализация базы", "Загружены демонстрационные данные")
        db.commit()
        print(f"Готово: {len(USERS)} сотрудников, {len(ITEMS)} позиций каталога.")
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    run_seed(force="--force" in sys.argv)
