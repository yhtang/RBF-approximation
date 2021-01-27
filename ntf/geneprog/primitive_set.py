#!/usr/bin/env python
# -*- coding: utf-8 -*-
import uuid
from abc import ABC, abstractmethod
import numpy as np
from deap import gp
from ntf.util.iterable import flatten, flatten_if, map_or_call


class PrimitiveSet:
    '''A DEAP primitive set for nonlinear tensor factorization.

    Parameters
    ----------
    ret_type: type
        Type of the overall factorization expression.
    rank_types: list
        The types of the vectors that make up one 'rank'.
    k: int
        Maximum number of ranks to be sought in the factorization.
    '''

    @staticmethod
    def new_type(name=None, bases=()):
        name = name or f'type{uuid.uuid4().hex}'
        return type(name, bases, {})

    class PrimitiveBase(ABC):

        @property
        @abstractmethod
        def action(self):
            pass

        def __init__(self, *operands, shape=None):
            self.operands = tuple(operands)

        def forward(self, grad=False):
            return self.action(*[o.forward(grad=grad) for o in self.operands])

    class TerminalBase(ABC):

        @property
        @abstractmethod
        def action(self):
            pass

        def __init__(self, shape):
            self._value = self.action(shape)

        def forward(self, grad=False):
            return self._value

    def __init__(self, ret_type):
        self.ret_type = ret_type
        self.pset = gp.PrimitiveSetTyped('factorization', [], ret_type)

    def from_string(self, string):
        return gp.PrimitiveTree.from_string(string, self.pset)

    def gen_expr(self, max_depth: int, p=None):
        '''Propose a candidate nonlinear factorization expression.

        Parameters
        ----------
        max_depth: int
            Maximum depth (number of layers) of the expression.
        p: dict or callable
            A lookup table of the relative frequencies of the primitives in the
            generated expression.

        Returns
        -------
        expr: list
            A factorization in the form of a prefix expression.
        '''
        return self._gen_expr(
            self.ret_type,
            p if p is not None else lambda _: 1.0,
            max_depth
        )

    def _gen_expr(self, t=None, p=None, d=0):
        if d <= 0:  # try to terminate ASAP
            try:
                choice = np.random.choice(self.pset.terminals[t], 1).item()
            except ValueError:
                choice = np.random.choice(self.pset.primitives[t], 1).item()
        else:  # normal growth
            candidates = self.pset.primitives[t] + self.pset.terminals[t]
            prob = np.fromiter(map_or_call(candidates, p), dtype=np.float)
            choice = np.random.choice(
                candidates, 1, p=prob / prob.sum()
            ).item()

        if isinstance(choice, gp.Terminal):
            return [choice]
        else:
            return [choice, *flatten([self._gen_expr(a, p=p, d=d-1)
                                      for a in choice.args])]

    def instantiate(self, expr, **kwargs):
        s, expr = expr[0], expr[1:]
        node_cls = self.pset.context[s.name]
        children = []
        for _ in range(s.arity):
            t, expr = self.instantiate(expr, **kwargs)
            children.append(t)
        node = node_cls(*children, **kwargs)
        return node, expr

    def add_primitive(self, ret_type, in_types=None, name=None, params=None,
                      hyper_params=None):

        def decorator(f):

            _params = params or []
            _hyper_params = hyper_params or []

            class Primitive:

                def __init__(self, *children, **kwargs):
                    self.__f = f(self, **{k: kwargs[k] for k in _hyper_params})
                    self.__c = children

                def __call__(self):
                    return self.__f(*[c() for c in self.__c])

                @property
                def params(self):
                    return [
                        getattr(self, p) for p in _params
                    ] + [
                        c.params for c in self.__c
                    ]

                @property
                def flat_params(self):
                    return flatten_if(
                        self.params,
                        lambda i: isinstance(i, list)
                    )

            if in_types is None:
                self.pset.addTerminal(Primitive, ret_type,
                                      name=name or f.__name__)
            else:
                self.pset.addPrimitive(Primitive, in_types, ret_type,
                                       name=name or f.__name__)

        return decorator

    def add_terminal(self, ret_type, name=None, params=None,
                     hyper_params=None):
        return self.add_primitive(
            ret_type, in_types=None, name=name, params=params,
            hyper_params=hyper_params
        )