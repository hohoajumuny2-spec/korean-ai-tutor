"""테스트용 가짜 Firestore. FirestoreStore가 쓰는 기능만 흉내 낸다."""
import copy
import threading


class AlreadyExists(Exception):
    pass


class Snap:
    def __init__(self, ref, data):
        self.reference, self._data = ref, data
        self.exists = data is not None
        self.id = ref.id

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class DocRef:
    def __init__(self, store, col, id_):
        self._s, self._c, self.id = store, col, id_

    def _docs(self):
        return self._s.data.setdefault(self._c, {})

    def get(self):
        return Snap(self, self._docs().get(self.id))

    def set(self, data, merge=False):
        with self._s.lock:
            for v in data.values():
                assert not isinstance(v, (set, tuple)), "Firestore에 넣을 수 없는 값"
            if merge and self.id in self._docs():
                self._docs()[self.id].update(copy.deepcopy(data))
            else:
                self._docs()[self.id] = copy.deepcopy(data)

    def create(self, data):
        with self._s.lock:
            if self.id in self._docs():
                raise AlreadyExists("Document already exists")
            self._docs()[self.id] = copy.deepcopy(data)

    def delete(self):
        self._docs().pop(self.id, None)


class Query:
    def __init__(self, store, col, conds=()):
        self._s, self._c, self._conds = store, col, conds

    def where(self, field, op, value):
        assert op == "=="
        return Query(self._s, self._c, self._conds + ((field, value),))

    def stream(self):
        for id_, d in list(self._s.data.get(self._c, {}).items()):
            if all(d.get(f) == v for f, v in self._conds):
                yield Snap(DocRef(self._s, self._c, id_), d)


class ColRef(Query):
    def document(self, id_):
        return DocRef(self._s, self._c, id_)


class FakeFirestore:
    def __init__(self):
        self.data, self.lock = {}, threading.RLock()

    def collection(self, name):
        return ColRef(self, name)
